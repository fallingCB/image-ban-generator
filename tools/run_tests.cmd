@echo off
REM Full verification: rebuild the page, then run every check.
setlocal
cd /d "%~dp0\.."

echo === rebuilding ban-sticker.html ===
python tools\build_page.py || exit /b 1
echo.
echo === core tests: quantiser + GIF encoder ===
node tools\test_core.js || exit /b 1

echo.
echo === page tests: geometry, placement, inlined assets ===
node tools\test_page.js || exit /b 1

echo.
echo === markup check: referenced ids exist, no external requests ===
node tools\check_dom.js || exit /b 1

echo.
echo === GIF files: encode in JS, decode with the verified reader + Pillow ===
node tools\make_test_gifs.js || exit /b 1
python tools\verify3.py || exit /b 1

echo.
echo === sample render ===
python tools\render_sample.py || exit /b 1

echo.
echo === end-to-end in headless Edge: nothing of the picture leaks outside the ring ===
python tools\browser_test.py || exit /b 1

echo.
echo === end-to-end in headless Edge: a real GIF through the real UI, out comes a real GIF ===
python tools\gif_e2e.py || exit /b 1

echo.
echo ALL CHECKS PASSED
