@echo off
REM Mining Dashboard - Setup Verification Script
REM This script checks if everything is configured correctly

echo ========================================
echo  Mining Dashboard - Setup Verification
echo ========================================
echo.

REM Check 1: Backend files
echo [1/6] Checking backend files...
if not exist "rest-api\main.py" (
    echo   X ERROR: rest-api/main.py not found!
    goto :error
)
if not exist "rest-api\.env" (
    echo   ! WARNING: rest-api/.env not found! You need to create it.
) else (
    echo   ✓ Backend files OK
)
echo.

REM Check 2: Frontend files
echo [2/6] Checking frontend files...
if not exist "frontend\package.json" (
    echo   X ERROR: frontend/package.json not found!
    goto :error
)
if not exist "frontend\.env" (
    echo   ! WARNING: frontend/.env not found! Should have been created.
) else (
    echo   ✓ Frontend files OK
)
echo.

REM Check 3: Startup scripts
echo [3/6] Checking startup scripts...
if not exist "rest-api\start-server.bat" (
    echo   X ERROR: rest-api/start-server.bat not found!
) else (
    echo   ✓ Startup scripts OK
)
echo.

REM Check 4: Check if port 8001 is available
echo [4/6] Checking port 8001 availability...
netstat -ano | findstr :8001 >nul 2>&1
if %errorlevel% equ 0 (
    echo   ! WARNING: Port 8001 is already in use!
    echo   ! Run: netstat -ano ^| findstr :8001
    echo   ! To see what's using it.
) else (
    echo   ✓ Port 8001 is available
)
echo.

REM Check 5: Check environment file content
echo [5/6] Checking frontend .env configuration...
if exist "frontend\.env" (
    findstr /C:"8001" frontend\.env >nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✓ Frontend .env has correct port (8001)
    ) else (
        echo   X ERROR: Frontend .env doesn't contain port 8001!
    )
) else (
    echo   X ERROR: frontend/.env not found!
)
echo.

REM Check 6: Node modules
echo [6/6] Checking frontend dependencies...
if not exist "frontend\node_modules" (
    echo   ! WARNING: Frontend dependencies not installed.
    echo   ! Run: cd frontend ^&^& npm install
) else (
    echo   ✓ Frontend dependencies OK
)
echo.

echo ========================================
echo  Verification Complete!
echo ========================================
echo.
echo Next Steps:
echo   1. Start backend:  cd rest-api ^&^& start-server.bat
echo   2. Start frontend: cd frontend ^&^& npm run dev
echo   3. Open browser:   http://localhost:3000
echo.
echo See QUICK-START.md for detailed instructions.
echo ========================================
pause
exit /b 0

:error
echo.
echo ========================================
echo  SETUP ERROR DETECTED
echo ========================================
echo.
echo Please check the error messages above.
echo See MIGRATION-SUMMARY.md for setup help.
echo.
pause
exit /b 1
