# Stocker Custom Integration for Home Assistant

A custom Home Assistant integration (domain `stocker_custom_integration`), installable via HACS or manually.

## Installation

**HACS:** add this repository as a custom repository (category *Integration*), install, then restart Home Assistant.

**Manual:** copy `custom_components/stocker_custom_integration` into your Home Assistant `config/custom_components/` folder and restart.

Then go to **Settings → Devices & Services → Add Integration** and search for *Stocker Custom Integration*.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements_dev.txt
pytest
```

## Structure

| File | Purpose |
| --- | --- |
| `__init__.py` | Entry setup/unload, platform forwarding |
| `config_flow.py` | UI setup flow |
| `coordinator.py` | Polls the data source on an interval |
| `sensor.py` | Sensor entities backed by the coordinator |
| `strings.json` / `translations/` | UI text |
