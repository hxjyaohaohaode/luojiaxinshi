"""A bounded SSE subscriber; browser disconnects do not cancel persisted work."""
import asyncio
from contextlib import aclosing
import logging


class StreamJob:
    def __init__(self, source, workers, heartbeat=15, on_finish=None):
        self.source=source
        self.queue=asyncio.Queue(maxsize=32)
        self.connected=True
        self.finished=False
        self.heartbeat=heartbeat
        self.on_finish=on_finish
        self.task=asyncio.create_task(self.run())
        workers.add(self.task)
        self.task.add_done_callback(workers.discard)
        self.task.add_done_callback(self.finalize)

    def finalize(self,task):
        # A Task cancelled before its first instruction never enters run() or
        # the async generator's finally block. Release ownership in that case too.
        self.finished=True
        if not task.cancelled():task.exception()
        if self.connected and self.queue.empty():self.queue.put_nowait(None)
        if self.on_finish:
            try:self.on_finish(task)
            except Exception:logging.getLogger('campus').error('stream_finalization_failed: check storage and permissions')

    async def run(self):
        try:
            async with aclosing(self.source):
                async for packet in self.source:
                    if self.connected:await self.queue.put(packet)
        finally:
            self.finished=True
            if self.connected:await self.queue.put(None)

    async def subscribe(self):
        try:
            while not self.finished or not self.queue.empty():
                try:packet=await asyncio.wait_for(self.queue.get(),self.heartbeat)
                except TimeoutError:
                    yield ': keepalive\n\n'
                    continue
                if packet is None:return
                yield packet
        finally:
            # Release any blocked put without retaining all future packets in memory.
            self.connected=False
            while not self.queue.empty():self.queue.get_nowait()
