"""Read one bounded provider response. Never publish incomplete JSON or reasoning."""
import codecs
import json

MAX_STREAM_BYTES = 8_000_000
MAX_EVENT_BYTES = 500_000
MAX_CONTENT_BYTES = 500_000


def read_reply(response, trace):
    trace.metrics['headers_seconds'] = trace.elapsed()
    if 'text/event-stream' not in response.headers.get('content-type', '').lower():
        trace.metrics['transport'] = 'json'
        chunks = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_CONTENT_BYTES:
                raise ValueError('response_too_large')
            chunks.append(chunk)
        data = json.loads(b''.join(chunks))
        if not isinstance(data, dict):
            raise ValueError('invalid_envelope')
        trace.usage(data.get('usage'))
        trace.metrics['provider_seconds'] = trace.elapsed()
        choices = data.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError('invalid_choice')
        choice = choices[0]
        message = choice.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('content'), str) or message.get('tool_calls'):
            raise ValueError('invalid_message')
        # A buffered reply provides no observable first-answer timing.
        trace.phase('receiving')
        return message['content'], choice.get('finish_reason')

    trace.metrics['transport'] = 'sse'
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    parts = []
    event_lines = []
    size = content_size = event_size = 0
    finish = None
    done = False

    def event(value):
        nonlocal finish, done, content_size
        if value.strip() == '[DONE]':
            done = True
            return
        packet = json.loads(value)
        if not isinstance(packet, dict) or packet.get('error'):
            raise ValueError('invalid_stream_packet')
        trace.usage(packet.get('usage'))
        choices = packet.get('choices', [])
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError('invalid_stream_choice')
        if not choices:
            return
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get('index', 0) != 0:
            raise ValueError('invalid_stream_choice')
        delta = choice.get('delta', {})
        if not isinstance(delta, dict) or delta.get('tool_calls'):
            raise ValueError('invalid_stream_delta')
        content = delta.get('content')
        if content is not None and not isinstance(content, str):
            raise ValueError('invalid_stream_content')
        if content:
            if finish is not None:
                raise ValueError('content_after_finish')
            content_size += len(content.encode('utf-8'))
            if content_size > MAX_CONTENT_BYTES:
                raise ValueError('content_too_large')
            trace.answer()
            parts.append(content)
        # Deliberately do not accumulate or pass through reasoning_content.
        reason = choice.get('finish_reason')
        if reason:
            if finish is not None or not isinstance(reason, str):
                raise ValueError('invalid_stream_finish')
            finish = reason

    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_STREAM_BYTES:
            raise ValueError('stream_too_large')
        buffer += decoder.decode(chunk)
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            line = line.removesuffix('\r')
            if len(line.encode('utf-8')) > MAX_EVENT_BYTES:
                raise ValueError('event_too_large')
            if not line:
                if event_lines:
                    event('\n'.join(event_lines))
                    event_lines = []
                    event_size = 0
                if done:
                    break
            elif line.startswith('data:'):
                value = line[5:].removeprefix(' ')
                event_size += len(value.encode('utf-8'))
                if event_size > MAX_EVENT_BYTES:
                    raise ValueError('event_too_large')
                event_lines.append(value)
        if done:
            break
        if len(buffer.encode('utf-8')) > MAX_EVENT_BYTES:
            raise ValueError('event_too_large')
    trace.metrics['provider_seconds'] = trace.elapsed()
    if not done or finish is None:
        raise ValueError('incomplete_stream')
    return ''.join(parts), finish
