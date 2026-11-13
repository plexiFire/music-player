import subprocess


def tone(path, secs=2, freq=440):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs}",
                    path], check=True)
    return path
