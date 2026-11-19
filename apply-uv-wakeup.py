"""Keep ready Windows libuv work on the main task runner."""
from pathlib import Path
import sys

FILE = 'shell/common/node_bindings.cc'
OLD = '''  // Tell the worker thread to continue polling.
  uv_sem_post(&embed_sem_);
}'''
NEW = '''#if BUILDFLAG(IS_WIN)
  // The embed thread stays parked while libuv already has ready work. Posting
  // one task per turn preserves Chromium fairness and still polls I/O in uv_run.
  if (uv_backend_timeout(uv_loop_) == 0) {
    WakeupMainThread();
    return;
  }
#endif
  // Tell the worker thread to continue polling.
  uv_sem_post(&embed_sem_);
}'''


def patch(root):
    file = Path(root) / FILE
    text = file.read_text(encoding='utf-8')
    if NEW in text or text.count(OLD) != 1:
        raise RuntimeError(f'{FILE}: expected exactly one patch anchor')
    file.write_text(text.replace(OLD, NEW), encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(sys.argv[1])
    print('Applied ready-work libuv wakeup bypass.')
