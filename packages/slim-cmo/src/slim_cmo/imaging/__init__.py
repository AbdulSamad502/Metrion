"""Image intake (P6): validate, normalise, strip metadata. Uses Pillow, so it sits OUTSIDE the pure core
(like `repositories/` and `providers/`); it still touches no network, database or clock."""
