from app import create_app
import socket
from contextlib import closing
import random

def find_free_port(start_range=5000, end_range=9000):
    """Find a free port in the given range"""
    while True:
        port = random.randint(start_range, end_range)
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                sock.bind(('', port))
                return port
            except OSError:
                continue

app = create_app()

if __name__ == "__main__":
    port = find_free_port()
    print(f"\nStarting server on port {port}")
    print(f"Access the application at: http://localhost:{port}\n")
    app.run(host='0.0.0.0', port=port)