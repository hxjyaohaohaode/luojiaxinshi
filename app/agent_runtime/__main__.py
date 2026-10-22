"""Noninteractive campus-agent exec. Credentials are read from the environment."""
import argparse
import asyncio
import json
import os
import sys

import httpx

from .sdk import Client, TERMINAL


def parser():
    root = argparse.ArgumentParser(prog='python -m app.agent_runtime')
    sub = root.add_subparsers(dest='command', required=True)
    run = sub.add_parser('exec', help='通过当前应用执行持久任务，默认拒绝写入和外部工具审批')
    run.add_argument('prompt', nargs='?', default='-')
    run.add_argument('--server', default='http://127.0.0.1:8765')
    run.add_argument('--username', required=True)
    run.add_argument('--resume', metavar='THREAD_ID')
    run.add_argument('--conversation', metavar='CONVERSATION_ID')
    run.add_argument('--runtime', action='store_true', help='显式使用底层工具运行时；默认走原聊天与独立证据复核')
    run.add_argument('--request-id', help='重试请求时使用同一标识，避免重复执行')
    run.add_argument('--json', action='store_true', help='以 JSONL 输出实际执行事件')
    run.add_argument('--oss', action='store_true', help='新会话使用已配置的本地模型；不会回退云端')
    run.add_argument('--allow-external-processing', action='store_true')
    run.add_argument('--skill', action='append', default=[])
    run.add_argument('--scope', action='append', choices=['library', 'schedule', 'memory'], default=[])
    return root


async def execute(args):
    password = os.getenv('CAMPUS_AGENT_PASSWORD', '')
    if not password:
        raise ValueError('请先在环境变量 CAMPUS_AGENT_PASSWORD 中设置账号密码；不接受命令行明文密码')
    prompt = sys.stdin.read(64001) if args.prompt == '-' else args.prompt
    if not prompt.strip() or len(prompt) > 16000:
        raise ValueError('任务内容须为 1—16000 字')
    if args.resume and (args.oss or args.conversation or args.skill or args.scope):
        raise ValueError('恢复会话保留原模型、资料范围和技能；这些选项只用于新会话')
    if not (args.runtime or args.oss or args.resume) and (args.skill or args.scope):
        raise ValueError('原聊天按问题自动选择技能与资料范围；固定范围/技能选项用于 --runtime 或 --oss')
    async with Client(args.server) as client:
        await client.login(args.username, password)
        if not (args.runtime or args.oss or args.resume):
            if len(prompt) > 6000:
                raise ValueError('原聊天每条消息最多 6000 字，请拆分或上传为材料')
            chat = client.conversation(args.conversation) if args.conversation else await client.start_conversation(prompt[:60])
            print('conversation_id=' + chat.id, file=sys.stderr)
            terminal, resolved = None, set()
            async for item in chat.run_streamed(prompt, allow_external_processing=args.allow_external_processing, request_id=args.request_id):
                if args.json:print(json.dumps(item, ensure_ascii=False), flush=True)
                if item['type'] == 'agent':
                    for approval in (item['data'].get('state') or {}).get('approvals', []):
                        if approval['id'] not in resolved:
                            await chat.approve(approval['id'], approval['digest'], 'deny');resolved.add(approval['id'])
                if item['type'] == 'done':terminal = item['data']['conversation']['messages'][-1]
            if terminal is None:
                raise RuntimeError('事件连接中断，请用 conversation_id 核对原聊天记录')
            if not args.json:print(terminal['content'] if terminal['status'] == 'complete' else terminal['error'])
            return 0 if terminal['status'] == 'complete' else 1
        thread = client.resume_thread(args.resume) if args.resume else await client.start_thread(
            provider='oss' if args.oss else 'mimo', conversation_id=args.conversation,
            title=prompt[:60], skills=args.skill, scopes=args.scope, approval_policy='deny')
        print('thread_id=' + thread.id, file=sys.stderr)
        terminal = None
        async for item in thread.run_streamed(prompt, allow_external_processing=args.allow_external_processing, request_id=args.request_id):
            if args.json:
                print(json.dumps(item, ensure_ascii=False), flush=True)
            if item['type'] == 'approval.requested':
                await thread.approve(item['data']['id'], item['data']['digest'], 'deny')
            if item['type'] in TERMINAL:
                terminal = item['data']
        if terminal is None:
            raise RuntimeError('事件连接中断；请通过会话标识核对已保存状态，不要以新标识重复收费任务')
        if not args.json:
            print(terminal['answer'] or terminal['error'])
        return 0 if terminal['status'] == 'completed' else 1


def main():
    try:
        return asyncio.run(execute(parser().parse_args()))
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get('detail', '应用请求失败')
        except ValueError:
            detail = '应用请求失败'
        print(f'HTTP {exc.response.status_code}: {detail}', file=sys.stderr)
    except httpx.HTTPError:
        print('无法连接工作台或事件流中断，请核对持久会话状态。', file=sys.stderr)
    except KeyboardInterrupt:
        print('客户端已退出；后台任务可能仍在执行，请在工作台核对或停止。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
