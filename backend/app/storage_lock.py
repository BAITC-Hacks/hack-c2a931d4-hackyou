"""One local API worker owns a storage directory, including its job recovery."""

import os
from pathlib import Path


class StorageLock:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.stream = (root / "worker.lock").open("a+b")
        try:
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise RuntimeError(
                "This storage directory is already used by another API worker"
            ) from error

    def close(self):
        self.stream.close()
