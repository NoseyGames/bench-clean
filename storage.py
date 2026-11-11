"""Cancellable, read-only directory accounting. Never follow reparse points."""
import heapq
import os
from pathlib import Path
import stat
import threading
import time


class Scanner:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.state = dict(status='idle', entries=[], largest=[], bytes=0, files=0, skipped=0)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, root):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Cancel or finish the current scan first.')
            self.cancel.clear()
            self.state = dict(status='running', root=str(root), entries=[], largest=[], bytes=0, files=0, skipped=0)
            self.thread = threading.Thread(target=self._scan, args=(Path(root),), daemon=True)
            self.thread.start()

    def _scan(self, root):
        totals, largest, directories = {}, [], set()
        files = skipped = total = 0
        stack = [(root, None)]
        last = 0

        def publish(status):
            with self.lock:
                self.state.update(status=status, bytes=total, files=files, skipped=skipped,
                                  entries=sorted([dict(path=k, size=v, directory=k in directories) for k, v in totals.items()],
                                                 key=lambda x: x['size'], reverse=True),
                                  largest=[dict(size=s, path=p) for s, p in sorted(largest, reverse=True)])
        try:
            while stack and not self.cancel.is_set():
                folder, bucket = stack.pop()
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if self.cancel.is_set():
                                break
                            try:
                                info = entry.stat(follow_symlinks=False)
                                if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                                    skipped += 1
                                    continue
                                group = bucket or entry.path
                                totals.setdefault(group, 0)
                                if stat.S_ISDIR(info.st_mode):
                                    if bucket is None:
                                        directories.add(group)
                                    stack.append((Path(entry.path), group))
                                elif stat.S_ISREG(info.st_mode):
                                    size = info.st_size
                                    files += 1
                                    total += size
                                    totals[group] += size
                                    heapq.heappush(largest, (size, entry.path))
                                    if len(largest) > 100:
                                        heapq.heappop(largest)
                            except OSError:
                                skipped += 1
                            if time.monotonic() - last > .5:
                                publish('running')
                                last = time.monotonic()
                except OSError:
                    skipped += 1
            publish('cancelled' if self.cancel.is_set() else 'complete')
        except Exception as exc:
            publish('failed')
            with self.lock:
                self.state['error'] = str(exc)
