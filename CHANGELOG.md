# Changelog

## v1.4.1 (2025-12-05)
- The new API implements a different scaling value behaviour. To preserve backwards compatibility, this new version 
aligns with the old behaviour.

## v1.4.0 (2025-12-05)
- The October 2025 release of WEO removed bulk downloads and moved everything towards the SDMX API. This update provides a way to parse new releases from the API instead of relying on the XML files. Note that thew new API response does not include observation-level notes or information on when projections start for each country-indicator.

## v1.3.0 (2025-2-05)
- Made function available to fetch latest holdings and allocations date
- Improved handling of unavailable dates

## v1.2.0 (2024-12-20)
- Add support for fetching Special Drawing Rights (SDR) data

## v1.1.0 (2024-10-11)
- Improved dtype handling for `fetch_data` function
- Improved error handling
- Improved logging

## v1.0.0 (2024-06-06)
- First stable release of `imf-reader` with full functionality for accessing WEO data

## v1.0.0b1 (2024-06-06)
- Beta release of `imf-reader` with full functionality for accessing WEO data

## v0.2.0 (2024-05-17)
- Basic functionality for accessing WEO data for initial testing

## v0.0.1 (2024-05-17)
- First release of `imf-reader`