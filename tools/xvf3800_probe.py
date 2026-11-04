"""Read-only probe of the reSpeaker XVF3800 on-chip direction of arrival (lot L44).

logging: robotlog.

Purpose  : prints whether the USB device is present, whether this account may open it (udev rule, see
           scripts/install-respeaker-udev.sh) and, when it can, N samples (default 10) of DOA_VALUE (degrees + speech
           flag), the four beam azimuths (radians) and the speech energies, with the mapped robot-frame azimuth.
Boundary : READ control transfers only (nanterino.sound.xvf3800.read_param); nothing is ever written to the chip, no
           audio stream is opened, the nanterino service is not contacted.
Usage    : .venv/bin/python tools/xvf3800_probe.py [N] [--sign -1]     (exit 0 = samples read, 2 = absent, 3 = no access)
"""
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, "/opt/robot/nanterino")
from robotlog import get_logger  # noqa: E402,F401

from nanterino.sound import xvf3800 as X  # noqa: E402


def main(argv):
    n = int(argv[0]) if argv and argv[0].lstrip("-").isdigit() else 10
    sign = -1.0 if "--sign" in argv and argv[argv.index("--sign") + 1].startswith("-") else 1.0
    dev = X.find_device()
    if dev is None:
        print("ABSENT : reSpeaker XVF3800 (2886:001a) introuvable (ou pyusb absent).")
        return 2
    try:
        X.read_param(dev, "DOA_VALUE")
    except Exception as e:   # noqa: BLE001
        print("PRESENT, ACCES REFUSE : %s" % Xvf(e))
        return 3
    print("PRESENT, ACCES OK. %d echantillons (doa deg, parole) | faisceaux rad | energies | azimut robot brut:" % n)
    for i in range(n):
        doa, flag = X.read_param(dev, "DOA_VALUE")
        beams = X.read_param(dev, "AEC_AZIMUTH_VALUES")
        energies = X.read_param(dev, "AEC_SPENERGY_VALUES")
        az, conf, _v, _lvl, _e = X.interpret(doa, flag, energies, sign, beams[3])
        print("%2d  doa=%3d speech=%d  beams=%s  energy=%s  az=%s conf=%.1f" % (
            i, doa, flag, [round(b, 3) for b in beams], [round(e, 4) for e in energies],
            "None" if az is None else "%.1f" % az, conf))
        time.sleep(0.1)
    return 0


def Xvf(e):
    return X.Xvf3800Source._explain(e)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
