# Failure: Jinja TemplateResponse signature regression on first VPS deploy

## Date
2026-04-24

## Trigger
First deploy of v1 vertical slice to VPS. Service started, OpenAPI 200, but `GET /` returned HTTP 500.

## Symptom
```
TypeError: unhashable type: 'dict'
  File ".../jinja2/environment.py", line 1016, in get_template
    return self._load_template(name, globals)
  File ".../jinja2/utils.py", line 477, in get
    return self[key]
  File ".../jinja2/utils.py", line 515, in __getitem__
    rv = self._mapping[key]
```

## Root cause
`derivation_web/api/views.py` used the legacy Starlette signature:
```python
templates.TemplateResponse("index.html", {"request": request})  # OLD
```
Starlette ≥ 0.30 (shipped with FastAPI 0.115) treats the first positional
arg as `request`, so the context dict landed where the template name was
expected. Jinja then tried to use the dict as a cache key — unhashable.

The bug shipped in the initial commit because **no test hit any
server-rendered route via TestClient**. mypy did not catch it because
`Jinja2Templates.TemplateResponse` is typed with `*args` and accepts
both signatures at the type level.

## Fix
Two-part:
1. Update all three view callers to the new signature:
   ```python
   templates.TemplateResponse(request, "index.html", {...})
   ```
2. Add `test_views_render` covering `/`, `/artifacts/{id}`,
   `/artifacts/{id}/chain` so the same regression fails loud next time.

Commit: `bb2a98e` (against `3d41fc5` initial).

## Prevention
- Server-rendered routes need at least one TestClient hit per route.
  Mypy + API-only contract tests do not provide this coverage.
- When adopting a new framework version, scan the changelog for
  signature deprecations, especially in functions typed as `*args`.

## Related skills / patterns
- Add a "render every Jinja route at least once" smoke step to any new
  FastAPI + Jinja project's bring-up checklist.
- The fixture stack already supported it; only the test was missing.
