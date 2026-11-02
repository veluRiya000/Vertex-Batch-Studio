!define /ifndef ERROR_MORE_DATA 234

!macro VBS_EnsureBinaryUnlocked executablePath componentName
  !define VBS_UID ${__LINE__}
  IfFileExists "${executablePath}" 0 vbs_done_${VBS_UID}

  !insertmacro RestartManager_StartSession $R0
  ${If} $R0 != ""
    !insertmacro RestartManager_RegisterFile $R0 "${executablePath}"
    ${If} $0 = 0
      System::Call 'RSTRTMGR::RmGetList(p R0, *i .r1, *i .r2, p 0, *i .r3) i .r0'
      ${If} $0 = ${ERROR_MORE_DATA}
        IfSilent vbs_kill_${VBS_UID} 0
        ${IfThen} $PassiveMode != 1 ${|} MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "检测到旧版 ${componentName} 后台尚未退出（${executablePath}）。$\r$\n$\r$\n点击“确定”将仅结束该安装目录下的占用进程并继续安装；点击“取消”中止安装。" IDOK vbs_kill_${VBS_UID} IDCANCEL vbs_cancel_${VBS_UID} ${|}
        vbs_kill_${VBS_UID}:
          System::Call 'RSTRTMGR::RmShutdown(p R0, i ${RmForceShutdown}, p 0) i .r0'
          ${If} $0 = 0
            Sleep 300
            Goto vbs_check_done_${VBS_UID}
          ${Else}
            !insertmacro RestartManager_EndSession $R0
            IfSilent 0 +2
              Abort
            MessageBox MB_ICONSTOP "无法结束占用 ${executablePath} 的旧版后台进程，请退出程序后重试。"
            Abort
          ${EndIf}
        vbs_cancel_${VBS_UID}:
          !insertmacro RestartManager_EndSession $R0
          Abort
        vbs_check_done_${VBS_UID}:
      ${EndIf}
    ${EndIf}
    !insertmacro RestartManager_EndSession $R0
  ${EndIf}

  vbs_done_${VBS_UID}:
  !undef VBS_UID
!macroend

!macro VBS_ENSURE_INSTDIR_UNLOCKED
  IfFileExists "$INSTDIR\backend\vertex-backend.exe" 0 vbs_skip_graceful_stop
    nsExec::ExecToStack '"$INSTDIR\backend\vertex-backend.exe" --root "$APPDATA\VertexBatchStudio" stop'
    Pop $0
    Pop $1
    Sleep 500
  vbs_skip_graceful_stop:

  !insertmacro VBS_EnsureBinaryUnlocked "$INSTDIR\harness\node\node.exe" "Vertex Batch Studio Harness"
  !insertmacro VBS_EnsureBinaryUnlocked "$INSTDIR\backend\vertex-backend.exe" "Vertex Batch Studio Backend"
  !insertmacro VBS_EnsureBinaryUnlocked "$INSTDIR\vertex-batch-studio.exe" "Vertex Batch Studio"
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro VBS_ENSURE_INSTDIR_UNLOCKED
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro VBS_ENSURE_INSTDIR_UNLOCKED
!macroend
