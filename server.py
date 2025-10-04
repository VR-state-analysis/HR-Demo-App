import http.server
import ssl
import argparse

# Parse command line arguments
parser = argparse.ArgumentParser(description='HTTPS server with SSL support')
parser.add_argument('--host', default='', help='Host address to bind to (default: all interfaces)')
parser.add_argument('--port', type=int, default=8000, help='Port number to bind to (default: 8000)')
parser.add_argument('--cert', default='cert.pem', help='Path to SSL certificate file (default: cert.pem)')
parser.add_argument('--key', default='key.pem', help='Path to SSL private key file (default: key.pem)')
args = parser.parse_args()

# Define the server address and port
server_address = (args.host, args.port)

# Create an SSL context
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER) 
# Load your certificate and private key
context.load_cert_chain(certfile=args.cert, keyfile=args.key)

# Create the HTTP server
with http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler) as httpd:
    # Wrap the server's socket with SSL
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    host_display = server_address[0] if server_address[0] else 'all interfaces'
    print(f"Serving HTTPS on {host_display}:{server_address[1]}")
    httpd.serve_forever()
