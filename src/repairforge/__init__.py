"""机械备件逆向重建与修复 v2 resource envelope, inherited by domain workers."""
import os
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='4'
if hasattr(os,'sched_getaffinity'):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
import cv2
cv2.setNumThreads(4)
