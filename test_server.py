#!/usr/bin/env python3
"""
PixivFavSearch 浏览器测试服务器（独立端口 8898）
用于在浏览器中测试 UI，不影响本地 8897 服务器
"""
import http.server
import socketserver
import os
import sys

PORT = 8898

# 固定路径到 PixivFavSearch-unified.html
_here = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(_here, "..", "PixivFavSearch-unified.html")
if not os.path.exists(HTML_PATH):
    HTML_PATH = os.path.join("C:", os.sep, "temp", "PixivFavSearch-unified.html")

class TestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if os.path.exists(HTML_PATH):
                with open(HTML_PATH, "r", encoding="utf-8") as f:
                    self.wfile.write(f.read().encode("utf-8"))
            else:
                self.wfile.write(f"<h1>Not found: {HTML_PATH}</h1>".encode("utf-8"))
        else:
            self.send_error(404)
    
    def log_message(self, format, *args):
        pass

def main():
    print(f"[测试服务器] Serving: {HTML_PATH}")
    print(f"[测试服务器] URL: http://127.0.0.1:{PORT}/")
    print("[测试服务器] Ctrl+C to stop")
    with socketserver.TCPServer(("127.0.0.1", PORT), TestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[测试服务器] 已停止")

if __name__ == "__main__":
    main()
