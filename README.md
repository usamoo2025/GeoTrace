 <div align="center">

# GeoTrace

### Visitor Information Gathering & Location Insights Platform

*An information-gathering web application built with FastAPI, featuring GPS location sharing, public IP information, and a centralized dashboard.*

![Platform](https://img.shields.io/badge/Platform-Web-blue)
![Language](https://img.shields.io/badge/Language-Python-yellow)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688)
![Database](https://img.shields.io/badge/Database-SQLite-blue)
![Frontend](https://img.shields.io/badge/Frontend-HTML%20%7C%20CSS%20%7C%20JavaScript-orange)
![License](https://img.shields.io/badge/License-GPL--3.0-blue)

[GitHub Repository](https://github.com/usamoo2025/GeoTrace) • [Report an Issue](https://github.com/usamoo2025/GeoTrace/issues) • [GitHub Profile](https://github.com/usamoo2025)

</div>

---

## About GeoTrace

GeoTrace is a web-based visitor information-gathering platform designed to collect, organize, and present information that visitors explicitly agree to share.

It provides a centralized dashboard for managing unique visit links and reviewing available visitor-submitted information, including GPS coordinates and public IP-related network metadata.

## Key Features

- **GPS Location Information** – Browser-based location readings with visitor permission.
- **IP & Network Information** – Public IP address and available ISP/provider information.
- **Geographic Insights** – Approximate country, region, and city information from IP metadata.
- **Unique Visit Links** – Generate and manage individual destination links.
- **Visitor Consent System** – Separate optional consent for GPS and IP information.
- **Interactive Dashboard** – View and manage submitted visit records.
- **Detailed Visit Records** – Inspect individual records and available information.
- **PDF Reports** – Export individual records and visit reports.
- **User Authentication** – Registration, login, and account-based record access.
- **Database Management** – Store and organize application information using SQLite.

## Technology Stack

- Python
- FastAPI
- SQLite
- HTML5
- CSS3
- JavaScript
- Jinja2
- Uvicorn
- ReportLab

## How It Works

1. Create a unique GeoTrace link.
2. Associate the link with a destination URL.
3. Share the link with the intended visitor.
4. The visitor reviews the information-sharing notice.
5. The visitor independently chooses whether to share GPS or public IP information.
6. Available consented information is processed and stored.
7. Review and manage records through the GeoTrace dashboard.

Visitors can decline optional information sharing and continue to the destination without creating a visit-information record.

## Privacy & Responsible Use

GeoTrace follows a consent-based information-sharing approach. GPS and IP information are separate optional categories, and visitors should be clearly informed before sharing either.

The application is intended for authorized information-gathering workflows, development, testing, and educational purposes. It should not be used for covert monitoring or collecting information without visitors' knowledge and agreement.

## License

GeoTrace is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

See the [LICENSE](LICENSE) file for the complete license terms.

**GeoTrace — Gather Responsibly. Understand Clearly. Respect Privacy.**