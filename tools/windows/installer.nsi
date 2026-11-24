; ReSrijan installer for Windows 10/11 (64-bit) – built on Linux by tools/windows/build_windows.py
; makensis -DVERSION=… -DAPPDIR=<folder to install> -DOUTFILE=<setup.exe> -DROOT=<repository> installer.nsi
Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ManifestDPIAware true
RequestExecutionLevel user

!include "MUI2.nsh"
!include "x64.nsh"

Name "ReSrijan ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\ReSrijan"
InstallDirRegKey HKCU "Software\ReSrijan" "InstallDir"
BrandingText "ReSrijan ${VERSION} – recreating scientific figures"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "ReSrijan"
VIAddVersionKey "FileDescription" "ReSrijan installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "RB Research Group"
VIAddVersionKey "LegalCopyright" "GNU AGPL v3 or later"

!define MUI_ICON "${APPDIR}\resrijan.ico"
!define MUI_UNICON "${APPDIR}\resrijan.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${APPDIR}\..\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${APPDIR}\..\wizard.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${APPDIR}\..\header.bmp"
!define MUI_HEADERIMAGE_RIGHT
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "ReSrijan ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "ReSrijan (पुनःसृजन, $\"re-creation$\") turns published scientific figures (PDF, EPS, SVG, PNG, JPG) back into data and redraws them in journal style.$\r$\n$\r$\nEverything it needs is included: Python, the figure engine, Tesseract OCR and Ghostscript. Nothing is uploaded anywhere.$\r$\n$\r$\nReSrijan is installed for your user account only; no administrator rights are needed."
!define MUI_FINISHPAGE_RUN "$INSTDIR\runtime\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m resrijan gui"
!define MUI_FINISHPAGE_RUN_TEXT "Start ReSrijan"
!define MUI_FINISHPAGE_LINK "Tutorials and source code"
!define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/rbiswasgroup/resrijan"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ROOT}\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "ReSrijan needs 64-bit Windows 10 or 11."
    Abort
  ${EndIf}
FunctionEnd

Section "ReSrijan (required)" SecMain
  SectionIn RO
  ; a previous version is replaced completely (your settings and templates are kept: they live elsewhere)
  RMDir /r "$INSTDIR\runtime"
  SetOutPath "$INSTDIR"
  File /r "${APPDIR}\*"
  WriteUninstaller "$INSTDIR\Uninstall ReSrijan.exe"

  CreateDirectory "$SMPROGRAMS\ReSrijan"
  CreateShortcut "$SMPROGRAMS\ReSrijan\ReSrijan.lnk" "$INSTDIR\runtime\pythonw.exe" "-m resrijan gui" "$INSTDIR\resrijan.ico" 0 SW_SHOWNORMAL "" "Turn published figures back into data"
  CreateShortcut "$SMPROGRAMS\ReSrijan\ReSrijan command prompt.lnk" "$SYSDIR\cmd.exe" '/k "set PATH=$INSTDIR;%PATH% && cd /d %USERPROFILE% && echo ReSrijan command line - try:  resrijan --help"' "$INSTDIR\resrijan.ico" 0
  CreateShortcut "$SMPROGRAMS\ReSrijan\Uninstall ReSrijan.lnk" "$INSTDIR\Uninstall ReSrijan.exe"

  WriteRegStr HKCU "Software\ReSrijan" "InstallDir" "$INSTDIR"
  !define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\ReSrijan"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "ReSrijan"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "RB Research Group"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\resrijan.ico"
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "URLInfoAbout" "https://github.com/rbiswasgroup/resrijan"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall ReSrijan.exe"'
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
  ; "Open with → ReSrijan" for figures
  WriteRegStr HKCU "Software\Classes\Applications\ReSrijan.figure\shell\open\command" "" '"$INSTDIR\runtime\pythonw.exe" -m resrijan gui "%1"'
  WriteRegStr HKCU "Software\Classes\Applications\ReSrijan.figure" "FriendlyAppName" "ReSrijan"
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\ReSrijan.lnk" "$INSTDIR\runtime\pythonw.exe" "-m resrijan gui" "$INSTDIR\resrijan.ico" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "The program, the command line and the bundled tools (Python, Qt, Tesseract, Ghostscript)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A ReSrijan icon on the desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\licenses"
  Delete "$INSTDIR\resrijan.cmd"
  Delete "$INSTDIR\resrijan.ico"
  Delete "$INSTDIR\Uninstall ReSrijan.exe"
  RMDir "$INSTDIR"
  RMDir /r "$SMPROGRAMS\ReSrijan"
  Delete "$DESKTOP\ReSrijan.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ReSrijan"
  DeleteRegKey HKCU "Software\Classes\Applications\ReSrijan.figure"
  DeleteRegKey HKCU "Software\ReSrijan\InstallDir"
SectionEnd
