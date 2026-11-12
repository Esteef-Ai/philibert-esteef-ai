"""WizTry entry point: --scan runs the CLI, otherwise it opens the app window."""
import sys

if __name__ == "__main__":
    if "--scan" in sys.argv:
        # Import the CLI lazily so a bare --scan run never pulls in the GUI.
        from wiztry.cli import main
        sys.exit(main(sys.argv[1:]))
    else:
        # The GUI branch runs only when --scan was NOT requested. Keep the
        # import inside this else so a --scan run can never reach it.
        try:
            from wiztry.app import main as app_main
            app_main()
        except ImportError:
            # No GUI on this build (only the CLI was built in this task).
            # Exit cleanly with a hint instead of a ModuleNotFoundError.
            print("The WizTry window is not available on this build; "
                  "use --scan to run the command line.")
            sys.exit(0)
