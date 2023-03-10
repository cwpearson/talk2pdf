import sys

import utils

dur = utils.video_duration(sys.argv[1])
utils.eprint(f'==== {dur}s')

for i in range(0, int(dur), 5):
    utils.eprint(f"==== frame @ {i}s")
    utils.extract_frame(f'frame-{i}.jpg', sys.argv[1], i)