# About

## What is CamTrap Verify?

**CamTrap Verify** is a lightweight, self-hosted web application that helps ecologists and wildlife researchers validate automatic species classifications produced by AI classifiers (such as [DeepFaune](https://www.deepfaune.cnrs.fr/)) or citizen-science platforms. It implements an **iterative, confidence-directed review** workflow that minimises the number of images an expert needs to inspect in order to reach reliable species-detection histories.

The tool is designed for researchers who work with camera-trap data formatted in the [CamtrapDP v1.0](https://camtrap-dp.tdwg.org/) standard and need to produce verified inputs for single-species occupancy models.

---

## Why iterative verification?

Classical manual verification requires an expert to review every single image — an impractical task when a season's dataset contains tens of thousands of frames. CamTrap Verify turns the problem around:

- It groups images into **sequences** (bursts of closely spaced frames) and ranks them by **classification confidence**.
- In round 1, the expert only sees the highest-confidence sequence per site × sampling-period × species cell. A single confirmation closes that cell — no further review needed.
- Rejected sequences trigger round 2 with the next-lowest-confidence sequence for the same cell.
- The process converges quickly: in practice, most cells are resolved in one or two rounds.

This means experts spend time on the images that *matter* — those on the boundary between true detections and false positives — rather than re-confirming obviously correct classifications.

---

## WildINTEL project

CamTrap Verify is developed as part of the **[WildINTEL](https://wildintel.eu/)** project, a transnational research initiative focused on improving biodiversity monitoring through the integration of passive acoustic monitoring, camera traps, and AI-assisted species identification.

WildINTEL is funded by the [Biodiversa+](https://www.biodiversa.eu/) Joint Research Call 2022-2023 *"Improved transnational monitoring of biodiversity and ecosystem change for science and society (BiodivMon)"* and has been co-funded by the European Commission (GA No. 101052342) together with the following national funding agencies:

| Country | Agency | Grant |
|---------|--------|-------|
| Spain | [Agencia Estatal de Investigación](https://www.aei.gob.es/) | PCI2023-145963-2, PCI2024-153489 |
| Poland | [National Science Centre](https://www.ncn.gov.pl/?language=en) | UMO-2023/05/Y/NZ8/00104 |
| Norway | [Research Council of Norway](https://www.forskningsradet.no/en/) | NFR350962 |
| Germany | [German Research Foundation](https://www.dfg.de/en/) | — |

---

## Data standard

CamTrap Verify is built around [**CamtrapDP v1.0**](https://camtrap-dp.tdwg.org/), the international standard for camera-trap data packages maintained by TDWG. Any dataset produced by a classifier that exports to CamtrapDP — including DeepFaune, Wildlife Insights, and Timelapse2 — can be loaded directly into CamTrap Verify without conversion.

---

## License

CamTrap Verify is free software released under the **GNU General Public License v3.0 or later**. You are free to use, modify, and redistribute it under the same terms.

---

## Citation

If you use CamTrap Verify in your research, please cite:

> WildINTEL Consortium (2026). *CamTrap Verify: iterative expert verification of camera-trap classifications*. https://wildintelproject.github.io/wildintel-trap-verify/

---

## Contact and contributions

- **Issues and feature requests**: [GitHub Issues](https://github.com/wildintelproject/wildintel-trapverify/issues)
- **Pull requests**: see the [Developer guide](developer.md)
- **Project website**: [wildintel.eu](https://wildintel.eu/)
