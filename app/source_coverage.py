"""Acquisition coverage shared by evidence, model context and pilot inspection.

Receiving original bytes, extracting text and verifying its meaning are separate
facts. A scan that needs visual review is not a missing attachment.
"""


def coverage(source):
    origin = source.get('origin') or {}
    received = set(origin.get('received_attachments') or [])
    readings = {item['url']: item for item in origin.get('attachment_reads', [])
                if isinstance(item, dict) and item.get('url')}
    missing = []
    for url in dict.fromkeys(origin.get('attachments') or []):
        if url not in received:
            item = readings.get(url) or {}
            missing.append({'url': url, 'label': item.get('label', ''),
                            'state': item.get('state', 'unavailable'),
                            'reason': item.get('reason', '本轮未取得该附件，不能据此推断内容')})
    related_errors = (origin.get('related_search') or {}).get('errors') or []
    failed = source.get('status') == 'failed'
    review = source.get('status') == 'review'
    retained = origin.get('retained_snapshots') or []
    incomplete = bool(missing or related_errors or failed or retained)
    return {'state': 'partial' if incomplete else 'review' if review else 'complete',
            'reading_incomplete': incomplete, 'review_required': review,
            'parse_failed': failed, 'attachment_total': len(set(origin.get('attachments') or [])),
            'attachment_received': len(set(origin.get('attachments') or []) & received),
            'unread_attachments': missing, 'related_errors': related_errors,
            'retained_snapshots': retained}
