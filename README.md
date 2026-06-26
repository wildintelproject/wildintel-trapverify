# <img src="docs/img/wildIntel_logo.webp" alt="WildINTEL Logo" height="60"> CamTrap Verify

![Python](https://img.shields.io/badge/python-3.13-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-blue.svg)
[![WildINTEL](https://img.shields.io/badge/WildINTEL-v1.0-blue)](https://wildintel.eu/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB)](https://react.dev/)
[![uv](https://img.shields.io/badge/uv-package_manager-5C4EE5)](https://github.com/astral-sh/uv)

<hr>

## Web tool for the iterative verification of camera trap classifications

**CamTrap Verify** is an open-source web application designed to help ecologists and wildlife researchers review and validate species detections produced by AI classifiers or citizen-science platforms. It consumes any directory in [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) format and guides the expert through a structured, iterative review workflow that minimises the total number of images that need to be inspected.

In each round, the tool presents the **highest-confidence sequence** not yet reviewed for every combination of site × sampling period × species. Confirming a sequence closes that cell; rejecting it queues the next-best sequence for the following round. This ensures that expert effort is always directed where it matters most — without having to look at every single image.

Once the review is complete, **CamTrap Verify** exports a verified CamtrapDP package with confirmed observations tagged as human classifications, together with detection histories and camera-operation matrices ready to feed directly into species occupancy models.

## ✨ Features

- Accepts any [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) directory — output from AI classifiers (e.g. DeepFaune) or citizen-science platforms
- Interactive image gallery with zoom, pan, tonal inversion and full keyboard navigation
- Iterative review by rounds: highest-confidence sequences always shown first
- Exports `camtrap_dp_verified/` with confirmed observations tagged as human classifications
- Generates naive vs. verified detection histories ready for occupancy models (`occupancy_inputs/`)
- Bilingual interface (Spanish / English)
- Docker deployment or hot-reload development mode

## 📋 Requirements

- Python 3.13+ with [uv](https://github.com/astral-sh/uv)
- Node.js 18+ / npm 9+
- Docker + Compose (production only)


## 📚 Documentation

Full documentation available at:
**https://wildintelproject.github.io/wildintel-trap-verify/**

## 🚀 Quick start

```bash
git clone <repo-url>
cd test-fastapi-truetype

# Install dependencies
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..

# Start in development mode
./start.sh dev
```

The browser will open at `http://localhost:5173`. See the [quick start guide](docs/quickstart.md) for a full walkthrough using the included example dataset.

## 🏛️ Funding

This work is part of the [WildINTEL project](https://wildintel.eu/), funded by the
[Biodiversa+](https://www.biodiversa.eu/) Joint Research Call 2022–2023
*"Improved transnational monitoring of biodiversity and ecosystem change for science and society (BiodivMon)"*.

## 📝 License

Dataset: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
Code: [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html)
