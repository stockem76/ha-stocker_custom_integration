# Face library tools

Helpers for seeding Frigate's Face Library from photos you already have. These tools never upload anywhere by themselves.

1. **Export photos into a bundle.** Google Photos only serves full images to a signed-in browser, so photos are fetched in the browser and saved as a single bundle file: `<image bytes...><index JSON><16-digit index length>`. Each index entry is `{folder, name, label, offset, len}`. Optionally, export each group's cover face (for example, a People tile) to `tiles/<group>.jpg`.
2. **Unpack the bundle:** `python unpack_bundle.py bundle.bin ROOT` writes `ROOT/raw/<group>/*.jpg`.
3. **Select faces:**
   ```bash
   python select_faces.py ROOT --models MODELS --tiles ROOT/tiles \
     --merge "Suzie=Suzie_1,Suzie_2" --exclude SomeGroup
   ```
   This needs `opencv-python` and `numpy`, plus OpenCV Zoo's `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx` in `MODELS`. It writes `ROOT/selected/<name>/*.jpg`, contact sheets in `ROOT/sheets/`, and `ROOT/report.json`.
4. **Review the contact sheets**, delete any bad crops, then upload the result to Frigate.

Keep `ROOT` outside this repository: it holds biometric data.
