"""WizTry - portable disk space analyzer."""

import sys

if "--scan" in sys.argv:
    from wiztry.cli import main
    sys.exit(main(sys.argv[1:]))

from wiztry import app
app.main()
