# Development camera samples

Place local JPEG sample images in this directory to use Phenopi without a
Raspberry Pi camera.

- `calibration.jpg` is the reserved camera-alignment and canopy-calibration
  preview.
- Every other `.jpg` or `.jpeg` file is a scheduled capture sample.
- Capture samples are consumed in natural filename order, so names such as
  `capture-001.jpg`, `capture-002.jpg`, and `capture-010.jpg` are recommended.
- Phenopi stops with a clear capture failure when the sequence is exhausted.

The images themselves are ignored by Git because camera datasets are large.
