import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    import jarvis

    jarvis.main(sys.argv[1:])
