import socket
import qrcode
import os

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

if __name__ == "__main__":
    ip = get_local_ip()
    port = 8000
    url = f"http://{ip}:{port}"
    
    print("=" * 40)
    print(f"📱 Connect your mobile device to:")
    print(f"   {url}")
    print("=" * 40)
    
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img_path = "local_connection_qr.png"
        img.save(img_path)
        
        # Open the image using the default image viewer on Windows
        os.startfile(img_path)
        print("📸 A QR code has been opened. Scan it with your phone's camera!")
    except Exception as e:
        print(f"Could not generate QR code: {e}")
