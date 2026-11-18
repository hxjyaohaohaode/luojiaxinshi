"""A single SSE reader can detach without holding up persisted work."""
import asyncio
from contextlib import aclosing
import logging


class StreamJob:
    def __init__(self, source, workers, heartbeat=15, on_finish=None, *, subscriber_timeout=5):
        self.source = source
        self.queue = asyncio.Queue(maxsize=32)
        self.connected = True
        self.finished = False
        self.heartbeat = heartbeat
        self.subscriber_timeout = subscriber_timeout
        self.on_finish = on_finish
        self.task = asyncio.create_task(self.run())
        workers.add(self.task)
        self.task.add_done_callback(workers.discard)
        self.task.add_done_callback(self.finalize)

    def detach(self):
        self.connected = False
        while not self.queue.empty():
            self.queue.get_nowait()
        # Wake a waiting reader. A partial stream ends without a done event,
        # which makes the browser reconcile the original turn from storage.
        self.queue.put_nowait(None)

    def finalize(self, task):
        self.finished = True
        if not task.cancelled():
            task.exception()
        if self.connected and self.queue.empty():
            self.queue.put_nowait(None)
        if self.on_finish:
            try:
                self.on_finish(task)
            except Exception:
                logging.getLogger('campus').error('stream_finalization_failed: check storage and permissions')

    async def deliver(self, packet):
        if not self.connected:
            return
        if not self.queue.full():
            self.queue.put_nowait(packet)
            return
        try:
            async with asyncio.timeout(self.subscriber_timeout):
                await self.queue.put(packet)
            if not self.connected:
                self.detach()
        except TimeoutError:
            self.detach()

    async def run(self):
        try:
            async with aclosing(self.source):
                async for packet in self.source:
                    await self.deliver(packet)
        finally:
            self.finished = True
            # A full queue already wakes subscribe(). It drains through the
            # last committed packet and observes finished without a second put.
            if self.connected and self.queue.empty():
                self.queue.put_nowait(None)

    async def subscribe(self):
        try:
            while self.connected and (not self.finished or not self.queue.empty()):
                try:
                    packet = await asyncio.wait_for(self.queue.get(), self.heartbeat)
                except TimeoutError:
                    yield ': keepalive\n\n'
                    continue
                if packet is None or not self.connected:
                    return
                yield packet
        finally:
            self.detach()
