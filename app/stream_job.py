"""A bounded SSE subscriber; browser disconnects do not cancel persisted work."""
import asyncio
from contextlib import aclosing


class StreamJob:
    def __init__(self, source, workers, heartbeat=15):
        self.source=source
        self.queue=asyncio.Queue(maxsize=32)
        self.connected=True
        self.finished=False
        self.heartbeat=heartbeat
        self.task=asyncio.create_task(self.run())
        workers.add(self.task)
        self.task.add_done_callback(workers.discard)

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
