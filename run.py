# Trivial little dev/testing runner because Xenial (the target platform) doesn't yet have the Flask dev binary

from control.webapp import app

def main():
    app.run(host="0.0.0.0")

if __name__ == "__main__":
    main()
