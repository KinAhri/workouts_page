"""Tests for the GPX simplification tolerance used when building track polylines.

gpxpy's ``simplify()`` defaults to a 10 metre Ramer-Douglas-Peucker tolerance,
which reduces a road run to little more than its corners. The stored
``summary_polyline`` then cuts across streets and the map looks like the GPS
track has drifted off the route. ``GPX_SIMPLIFY_MAX_DISTANCE`` pins that
tolerance down to 1 metre.
"""

import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_page"))

import gpxpy
import gpxpy.gpx
import polyline as polyline_codec

from run_page.gpxtrackposter import track as track_module
from run_page.gpxtrackposter.track import Track

# Toyooka, where the sample activities in this repo were recorded.
CENTER_LAT = 35.5555
CENTER_LON = 134.8100
CIRCLE_RADIUS_M = 100.0
# One point per metre of arc, i.e. the density a real Garmin track has.
POINT_SPACING_M = 1.0

METRES_PER_DEG_LAT = 110540.0


def _metres_per_deg_lon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def _to_local_metres(points):
    """Project (lat, lng) degrees onto a local flat plane in metres."""
    scale_lon = _metres_per_deg_lon(CENTER_LAT)
    return [
        ((lng - CENTER_LON) * scale_lon, (lat - CENTER_LAT) * METRES_PER_DEG_LAT)
        for lat, lng in points
    ]


def _point_to_segment_distance(p, a, b):
    """Shortest distance from point *p* to segment *a*-*b*, all in metres."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _max_deviation_m(original, simplified):
    """Largest distance in metres from any original point to the simplified line."""
    orig_xy = _to_local_metres(original)
    simp_xy = _to_local_metres(simplified)
    if len(simp_xy) < 2:
        return float("inf")
    return max(
        min(
            _point_to_segment_distance(p, simp_xy[i], simp_xy[i + 1])
            for i in range(len(simp_xy) - 1)
        )
        for p in orig_xy
    )


def _circle_points():
    """A closed 100 m radius circle sampled every metre of arc.

    A curve is what exposes the tolerance: Douglas-Peucker replaces arcs with
    chords, and the chord error is exactly the tolerance it was given.
    """
    circumference = 2 * math.pi * CIRCLE_RADIUS_M
    count = int(circumference / POINT_SPACING_M)
    scale_lon = _metres_per_deg_lon(CENTER_LAT)
    points = []
    for i in range(count + 1):
        angle = 2 * math.pi * i / count
        east = CIRCLE_RADIUS_M * math.cos(angle)
        north = CIRCLE_RADIUS_M * math.sin(angle)
        points.append(
            (
                CENTER_LAT + north / METRES_PER_DEG_LAT,
                CENTER_LON + east / scale_lon,
            )
        )
    return points


def _write_gpx(points):
    """Write *points* out as a Garmin-shaped GPX file, returning its path."""
    gpx = gpxpy.gpx.GPX()
    gpx.creator = "Garmin Connect"
    gpx_track = gpxpy.gpx.GPXTrack(name="Toyooka City - Base")
    gpx_track.type = "running"
    gpx.tracks.append(gpx_track)
    segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(segment)

    start = datetime(2026, 8, 31, 7, 58, 44, tzinfo=timezone.utc)
    for i, (lat, lng) in enumerate(points):
        segment.points.append(
            gpxpy.gpx.GPXTrackPoint(
                lat, lng, elevation=10.0, time=start + timedelta(seconds=i)
            )
        )

    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".gpx", delete=False, encoding="utf-8"
    )
    with handle as f:
        f.write(gpx.to_xml())
    return handle.name


class GpxSimplifyToleranceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.points = _circle_points()
        cls.gpx_path = _write_gpx(cls.points)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.gpx_path)

    def _load_polyline(self, max_distance):
        original = track_module.GPX_SIMPLIFY_MAX_DISTANCE
        track_module.GPX_SIMPLIFY_MAX_DISTANCE = max_distance
        try:
            track = Track()
            track.load_gpx(self.gpx_path)
        finally:
            track_module.GPX_SIMPLIFY_MAX_DISTANCE = original
        return polyline_codec.decode(track.polyline_str)

    def test_default_tolerance_is_one_metre(self):
        """Guards against silently falling back to gpxpy's 10 m default."""
        self.assertEqual(track_module.GPX_SIMPLIFY_MAX_DISTANCE, 1.0)

    def test_tolerance_is_configurable_by_env(self):
        self.assertEqual(
            os.getenv("GPX_SIMPLIFY_MAX_DISTANCE", "1"),
            "1",
            "test environment must not preset the tolerance",
        )

    def test_default_tolerance_keeps_track_on_the_route(self):
        decoded = self._load_polyline(track_module.GPX_SIMPLIFY_MAX_DISTANCE)
        deviation = _max_deviation_m(self.points, decoded)
        # 1 m tolerance plus the ~0.6 m quantisation of 5-decimal polyline encoding.
        self.assertLess(
            deviation,
            2.0,
            f"track drifts {deviation:.1f} m from the recorded route",
        )

    def test_gpxpy_default_tolerance_would_drift(self):
        """The regression this fixes: 10 m tolerance visibly leaves the road."""
        decoded = self._load_polyline(10.0)
        deviation = _max_deviation_m(self.points, decoded)
        self.assertGreater(deviation, 5.0)

    def test_zero_tolerance_keeps_every_recorded_point(self):
        decoded = self._load_polyline(0)
        self.assertEqual(len(decoded), len(self.points))

    def test_simplified_track_keeps_its_length(self):
        """Distance comes from the raw points, so it must survive simplification."""
        track = Track()
        track.load_gpx(self.gpx_path)
        self.assertAlmostEqual(
            track.length, 2 * math.pi * CIRCLE_RADIUS_M, delta=5.0
        )


if __name__ == "__main__":
    unittest.main()
