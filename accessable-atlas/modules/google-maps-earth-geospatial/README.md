# Module: Google Maps & Earth Geospatial (`modules/google-maps-earth-geospatial`)

## Purpose
Integrates **Google Maps Platform** (Wheelchair Transit Directions, Street View 360° Curb & Entrance Panorama, Elevation API) and **Google Earth 3D** (`<LookAt>` camera tilt flyovers and OGC KML 2.2 3D exports) with ADA $1:12$ ($4.76^\circ$) ramp slope and curb-to-entrance threshold verification.

## Boundary Contracts
- **Boundary Schema:** [`GeospatialRouteQuerySchema`](../../atlas/schemas.py) (`origin_lat`, `origin_lng`, `origin_label`, `travel_mode`)
- **Adapter:** [`GoogleMapsEarthAdapter`](../../atlas/adapters/google_maps_adapter.py)
- **HTTP Endpoints:**
  - `GET /api/venues/<id>/geospatial` & `POST /api/venues/<id>/geospatial`
  - `GET /api/venues/<id>/earth.kml`
  - `GET /api/export/earth.kml`

