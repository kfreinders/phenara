# Phenara

Phenara is a Raspberry Pi-based platform for reproducible, time-lapse plant
phenotyping. It combines scheduled image capture, camera alignment, canopy
segmentation, region-of-interest calibration, experiment storage, and a
browser-based control interface in one self-contained system.

The project is designed for top-view imaging of trays containing multiple
plants. Instead of assembling an experiment from configuration files and
separate command-line tools, Phenara guides the researcher through the full
workflow in the browser: define when images should be captured, verify the
camera view, calibrate the analysis, and review the experiment before it is
handed to the scheduler. Once activated, the same interface shows capture
progress and system state until the dataset is ready to export.

Reproducibility is treated as part of that workflow. Each experiment keeps its
schedule, capture settings, analysis configuration, ROI definition, outcomes,
and archive metadata together. Completed experiments remain available in a
history ledger, where a previous configuration can be inspected or used as the
starting point for a new run without re-entering it by hand.

## What Phenara provides

Phenara combines three roles that would otherwise have to be managed
separately. The browser interface is used to prepare and calibrate an
experiment, including flexible capture schedules, replicate images, camera
alignment, canopy segmentation, and ROI-grid definition. The persistent
scheduler then runs independently of the browser, with heartbeat monitoring,
missed-run handling, safe schedule replacement, and process-level protection
against concurrent camera access.

During acquisition, each run is kept in its own experiment directory together
with its metadata and analysis output. When the run is complete, Phenara
packages the dataset as a ZIP archive and only removes the local copy after
explicit confirmation that the archive has been saved elsewhere.

A retained experiment ledger stores the latest 200 completed experiment
records, including schedules, capture summaries, analysis settings, checksums,
and other reproducibility metadata. Historical configurations can be reused
through **Use this configuration**, while compact recovery records allow the
ledger to be reconstructed if its SQLite registry is lost.

For development and deployment, the same workflow can run with local JPEG
files in place of a Raspberry Pi camera. Production installations are provided
as systemd services, with an optional direct-Ethernet setup for appliance-like
operation.

## System overview

```text
Browser
   │
   ▼
FastAPI + React GUI ──────► schedule draft / commands / previews
   │                                      │
   │                                      ▼
   └──────────────────────────► persistent scheduler
                                          │
                              Raspberry Pi camera
                                          │
                                          ▼
                         captures/<experiment-id>/
                              images + metadata + results
                                          │
                         download ZIP and confirm cleanup
                                          │
                                          ▼
                         retained experiment-history ledger
```

The GUI and scheduler are separate processes. They communicate through
validated files in `runtime/`, while experiment data is written beneath
`captures/`. Atomic file replacement and process-level camera locking protect
the active workflow against partial writes and concurrent camera access.

## Requirements

### Production hardware

- A Raspberry Pi supported by `picamera2`.
- A compatible Raspberry Pi camera.
- Storage sized for the expected image count. Production captures default to
  4608 × 2592 JPEG images.
- A stable top-view camera mount and consistent illumination.
- Network access through Wi-Fi, an existing LAN, or a direct Ethernet cable.

The repository also contains FreeCAD design files in `hardware/` for the
project's physical rig and adapters. They are reference designs, not a required
software dependency.

### Software

- A Debian-based Raspberry Pi OS or comparable Linux system.
- Python 3 with virtual-environment support.
- Node.js and npm.
- `python3-picamera2` on a Raspberry Pi.
- systemd for the production service installation.
- NetworkManager only when using the provided direct-Ethernet helper.

Python packages are pinned by compatible version ranges in
`requirements.txt`. The main stack includes FastAPI, APScheduler, SQLAlchemy,
OpenCV, PlantCV, NumPy, pandas, SciPy, statsmodels, and Matplotlib.

## Production installation

Clone the repository into a permanent location owned by the account that will
run Phenara:

```bash
git clone https://github.com/kfreinders/phenopi.git
cd phenopi
sudo ./deploy/install.sh
```

Run the installer through `sudo` from the intended service account. Do not log
in as root and invoke it directly: the installer uses the calling account as
the owner of the project, virtual environment, runtime state, and captures.

The installer:

1. Installs required apt packages, including `python3-picamera2` when running
   on a Raspberry Pi.
2. Creates `.venv/` with access to system packages.
3. Installs the Python requirements.
4. Installs and builds the React frontend.
5. Creates `runtime/` and `captures/`.
6. Writes `/etc/phenara/phenara.env`.
7. Installs and enables `phenara-gui.service` and
   `phenara-scheduler.service`.
8. Starts both services unless `--no-start` was supplied.

Useful installer options:

```bash
sudo ./deploy/install.sh --no-start
sudo ./deploy/install.sh --skip-system-packages
sudo ./deploy/install.sh --enable-development-mode
```

Path, timezone, and network settings can be overridden for the installer with
the environment variables documented under [Configuration](#configuration).
For example:

```bash
sudo env PHENARA_TIMEZONE=Europe/London PHENARA_GUI_PORT=8080 \
  ./deploy/install.sh
```

After installation, open the address printed by the installer, normally:

```text
http://<raspberry-pi-address>:8000/
```

### Service administration

```bash
sudo systemctl status phenara-scheduler phenara-gui
sudo systemctl restart phenara-scheduler phenara-gui
sudo journalctl -u phenara-scheduler -f
sudo journalctl -u phenara-gui -f
```

Both services restart automatically after a failure and start at boot. Their
systemd units restrict filesystem writes to the configured runtime and capture
directories.

### Direct Ethernet connection

On systems using NetworkManager, Phenara can configure a wired connection that
provides DHCP to a directly connected laptop:

```bash
./deploy/configure-direct-ethernet.sh
```

The default Pi address is `192.168.50.2/24`. The helper schedules the reconnect
through systemd so the operation continues when the current SSH connection
drops. Custom values are supported:

```bash
./deploy/configure-direct-ethernet.sh \
  --connection "Wired connection 1" \
  --address 192.168.50.2/24 \
  --delay 10
```

Set the laptop's wired adapter to automatic/DHCP, then visit
`http://192.168.50.2:8000/`.

## Running without systemd

For development or a temporary installation, create an environment, install
the dependencies, and start both processes with the bundled launcher:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt
npm --prefix gui/frontend ci
./deploy/run-phenara.sh
```

The launcher builds the frontend, starts the web interface, starts the
scheduler, and stops both when either process exits or Ctrl+C is pressed.

To run the processes separately:

```bash
npm --prefix gui/frontend run build
.venv/bin/python -m gui.app
.venv/bin/python -m scripts.scheduling.scheduler
```

## Using Phenara

### 1. Create an experiment

Open **Experiments** and start a new schedule. The schedule builder first
collects the experiment name, researcher, dates, and notes, then guides the
capture timing and replicate settings. Capture times can be expressed as a
regular interval between two daily times, a fixed-duration window, a window
centered on a chosen time, or a set of explicit custom times.

<!-- Screenshot placeholder: schedule builder — experiment details -->
![Schedule builder: experiment details](docs/images/schedule-builder-details.png)

<!-- Screenshot placeholder: schedule builder — capture timing -->
![Schedule builder: capture timing](docs/images/schedule-builder-timing.png)

Before anything is activated, the review step expands these choices into the
actual capture plan and estimates the storage required for the run. This makes
the schedule inspectable as a concrete experiment rather than only as a set of
input parameters.

<!-- Screenshot placeholder: schedule builder — review -->
![Schedule builder: review](docs/images/schedule-builder-review.png)

### 2. Align the camera

Acquire a preview from the production camera and verify that the complete tray
is level, visible, and consistently framed. Alignment belongs to the schedule,
so changing or reusing a configuration requires a fresh confirmation rather
than silently carrying an old camera setup into a new run.

<!-- Screenshot placeholder: schedule builder — camera alignment -->
![Schedule builder: camera alignment](docs/images/schedule-builder-alignment.png)

### 3. Calibrate canopy analysis

If automated analysis is enabled, the same setup flow continues with canopy
segmentation and the plant ROI grid. These controls operate directly on the
camera image so the analysis can be checked against the material that will
actually be captured. The complete analysis configuration and ROI definition
are then stored with the experiment.

<!-- Screenshot placeholder: schedule builder — analysis calibration -->
![Schedule builder: analysis calibration](docs/images/schedule-builder-analysis.png)

### 4. Activate and monitor

Once the draft has been reviewed and calibrated, it can be activated. From
that point the scheduler runs independently of the browser, while the
experiment overview provides a single place to see service health, the active
run, capture progress, recent outcomes, storage state, and the next action
required from the researcher.

<!-- Screenshot placeholder: active experiment overview -->
![Active experiment overview](docs/images/active-experiment-overview.png)

Only one experiment owns the capture area at a time. Phenara therefore blocks
a new activation while raw files from a previous experiment still require
export and cleanup.

### 5. Export and clean up

When an experiment reaches a terminal state, Phenara prepares a ZIP archive.
Download it and store it somewhere durable. The cleanup action requires an
explicit confirmation that the archive was saved before Phenara removes both
the raw experiment directory and its local ZIP.

This is intentional: the Raspberry Pi is an acquisition system, not the
long-term home of the raw dataset.

### 6. Review or reproduce an experiment

Completed runs remain visible on the **History** page instead of disappearing
after their raw files have been exported. The ledger keeps the latest 200
terminal experiment records and ties each run to its schedule, researcher and
notes, capture outcomes, analysis configuration, ROI metadata, archive name,
size, SHA-256 checksum, and relevant timestamps.

<!-- Screenshot placeholder: experiment ledger / History page -->
![Experiment ledger](docs/images/experiment-ledger.png)

A historical run can also serve as a reproducible starting point. Selecting
**Use this configuration** creates a new draft with the previous settings,
shifts the schedule to new dates, and assigns a new run identity. Camera
alignment is deliberately returned to an unconfirmed state so the physical
setup must still be checked for the new experiment.

## Data retention and recovery

Phenara separates replaceable runtime state from retained experimental
metadata:

| Location | Purpose | Retention |
| --- | --- | --- |
| `runtime/schedule.json` | Active schedule | Replaced as experiments change |
| `runtime/schedule-draft.json` | In-progress schedule draft | Until discarded, activated, or replaced |
| `runtime/experiment-registry.sqlite` | Searchable experiment ledger | Latest 200 terminal records plus active state |
| `captures/<run-id>/` | Raw captures, run metadata, analysis output | Until confirmed export cleanup |
| `captures/<run-id>.zip` | Downloadable experiment archive | Until confirmed export cleanup |
| `captures/.phenara-deleted-runs/` | Compact recovery records | Latest 200 deleted experiments |

The recovery records preserve the schedule and metadata needed to reconstruct
history if `runtime/experiment-registry.sqlite` is lost. They do not retain raw
images. When more than 200 terminal experiments are recorded, the oldest
metadata is pruned.

Back up downloaded ZIP files independently. A history record and its SHA-256
checksum can prove which archive was exported, but cannot recreate deleted raw
images.

## Development mode

Development mode makes the complete scheduling and analysis workflow usable
without a Pi camera.

1. Put a calibration image at
   `development/sample-images/calibration.jpg`.
2. Add scheduled sample captures as `.jpg` or `.jpeg` files in the same
   directory. They are consumed in natural filename order; names such as
   `capture-001.jpg`, `capture-002.jpg`, and `capture-010.jpg` work well.
3. Start Phenara with development mode available:

```bash
./deploy/run-phenara.sh --enable-development-mode
```

4. Enable sample images from the development control in the interface.

The sample images themselves are ignored by Git. Once the sequence is
exhausted, additional simulated captures fail explicitly rather than silently
reusing an image. Simulated datasets contain a marker identifying them as
development data.

Never enable development mode on a production acquisition system unless sample
captures are genuinely intended.

## Configuration

Phenara uses one environment-driven configuration shared by the GUI,
scheduler, capture process, and installer.

| Variable | Default | Description |
| --- | --- | --- |
| `PHENARA_ROOT` | Repository root | Application source and asset directory |
| `PHENARA_RUNTIME_DIR` | `<root>/runtime` | Schedules, heartbeat, commands, previews, and registry |
| `PHENARA_CAPTURE_DIR` | `<root>/captures` | Experiment directories, archives, and recovery records |
| `PHENARA_VENV_DIR` | `<root>/.venv` | Python virtual environment |
| `PHENARA_PYTHON` | Current interpreter or venv Python | Interpreter used for scheduled captures |
| `PHENARA_DEVELOPMENT_IMAGE_DIR` | `<root>/development/sample-images` | Simulated camera inputs |
| `PHENARA_DEVELOPMENT_AVAILABLE` | `false` | Whether the GUI may enable development mode |
| `PHENARA_TIMEZONE` | `Europe/Amsterdam` | IANA timezone used for schedule interpretation |
| `PHENARA_GUI_HOST` | `0.0.0.0` | Web server bind address |
| `PHENARA_GUI_PORT` | `8000` | Web server port |

Production installs store these values in `/etc/phenara/phenara.env`. After
editing that file, restart both services.

## Command-line tools

The web interface is the recommended operational path, but the core tools can
also be run directly.

Generate a schedule:

```bash
.venv/bin/python -m scripts.scheduling.make_schedule every \
  --start 09:00 \
  --end 17:00 \
  --step-minutes 30 \
  --start-date 2026-08-19 \
  --num-days 7 \
  --replicates 3 \
  --replicate-interval-seconds 10 \
  --output runtime/schedule.json
```

Capture one image:

```bash
.venv/bin/python -m scripts.capture.capture_once \
  --output-dir captures/manual-test
```

Analyze one or more top-view images:

```bash
.venv/bin/python -m scripts.analysis.analyze_canopy \
  captures/manual-test/capture_*.jpg \
  --outdir results/manual-test
```

Plot canopy area and absolute growth rate:

```bash
.venv/bin/python -m scripts.plotting.plot_average_canopy_area \
  --input results/combined_traits.csv \
  --output results/average_canopy_area_vs_time.png
```

Each tool provides its complete option list through `--help`.

## Testing and frontend development

Run the Python suite from the repository root:

```bash
.venv/bin/python -m pytest -q
```

Run the frontend tests and production build:

```bash
npm --prefix gui/frontend test
npm --prefix gui/frontend run build
```

For live frontend development, start the backend and Vite development server in
separate terminals:

```bash
.venv/bin/python -m gui.app
npm --prefix gui/frontend run dev
```

The Vite configuration proxies API requests to the local FastAPI service.

## Repository layout

```text
phenara/                     Shared environment and development configuration
gui/
  app.py                     FastAPI application and React asset server
  routes/                    HTTP API endpoints
  services/                  Scheduling, preview, export, and status services
  frontend/                  React/Vite application
scripts/
  capture/                   Camera capture entry point
  scheduling/                Schedule model, scheduler, ledger, and run storage
  analysis/                  Canopy analysis and validation utilities
  plotting/                  Growth-curve plotting
deploy/                      Installer, launcher, network helper, systemd units
development/sample-images/   Local camera substitutes for development mode
hardware/                    FreeCAD rig and adapter models
docs/                        LaTeX project manual
tests/                       Python test suite
runtime/                     Generated operational state; not source-controlled
captures/                    Generated experiment data; not source-controlled
```

## Operational notes

Phenara assumes that the Raspberry Pi clock and timezone are correct when a
schedule is activated, because capture timing is based on wall-clock time.
During an experiment, keep the camera, tray position, illumination, and ROI
layout unchanged so that images remain comparable across the run.

The downloaded ZIP should be treated as the authoritative raw dataset. Verify
that it has been stored somewhere durable before confirming cleanup in
Phenara. If the system experiences a power loss or unexpected restart, review
the scheduler and GUI journals before continuing normal operation.

The web interface is intended for use on a trusted local network and should
not be exposed directly to the public internet. Files inside `runtime/` or an
active experiment directory should likewise not be edited manually while the
services are running.

## Documentation

The extended technical and operational manual lives in `docs/`. It covers the
system layout, installation, operation, canopy analysis, and growth-curve
plotting in greater depth.

Phenara is research instrumentation. Validate the complete acquisition and
analysis workflow against your own biological material, camera geometry, and
experimental design before relying on it for a study.

