; 南邮校园网 安装脚本（Inno Setup 6）
; 编译：ISCC.exe NJUPT_NET.iss

#define AppName "南邮校园网"
#define AppShortName "NJUPT_NET"

#define AppPublisher "1EM0NS"
#define AppUrl "https://github.com/1EM0NS/NJUPT_NET"
#define AppExeName "NJUPT_NET.exe"
#define PublishDir AddBackslash(SourcePath) + "..\publish"

#if !FileExists(PublishDir + "\" + AppExeName)
  #error 未找到 publish 目录，请先执行 dotnet publish
#endif

; 版本号只维护一处：从已发布 exe 的 ProductVersion 读取（来自 csproj 的 <Version>），
; 避免安装包和程序版本不一致。
#define AppVersionMajor
#define AppVersionMinor
#define AppVersionRev
#define AppVersionBuild
#define AppVersionInfo GetVersionComponents(PublishDir + "\" + AppExeName, \
  AppVersionMajor, AppVersionMinor, AppVersionRev, AppVersionBuild)
#if AppVersionInfo == ""
  #error 未能从已发布程序读取版本号
#endif
#define AppVersion Str(AppVersionMajor) + "." + Str(AppVersionMinor) + "." + Str(AppVersionRev)

[Setup]
AppId={{8D3C1F52-6B7A-4E1C-9A2D-5F0C7B41E9A3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 安装程序
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

DefaultDirName={autopf}\NJUPT_NET
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no

; 用户可在安装时选择「仅为我安装」或「为所有用户安装」
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\dist
OutputBaseFilename=NJUPT_Net_Setup_v{#AppVersion}
SetupIconFile=..\Resources\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Uninstallable=yes

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=yes
SetupLogging=yes
AllowNoIcons=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PublishDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "登录南邮校园网"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "登录南邮校园网"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  DotnetDownloadUrl = 'https://dotnet.microsoft.com/zh-cn/download/dotnet/8.0';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValueName = 'NJUPT_NET';

function HasDesktopRuntime(): Boolean;
var
  FindRec: TFindRec;
  BaseDir: String;
begin
  Result := False;
  BaseDir := ExpandConstant('{commonpf64}\dotnet\shared\Microsoft.WindowsDesktop.App');
  if not DirExists(BaseDir) then
    Exit;

  if FindFirst(BaseDir + '\8.*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if HasDesktopRuntime() then
    Exit;

  if MsgBox('未检测到 .NET 8 桌面运行时（Desktop Runtime）。' + #13#10 + #13#10 +
            '本版本为框架依赖安装包，需要先安装 .NET 8 Desktop Runtime 才能运行。' + #13#10 +
            '是否现在打开官方下载页面？', mbConfirmation, MB_YESNO) = IDYES then
  begin
    ShellExec('open', DotnetDownloadUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;

  Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  RegDeleteValue(HKCU, RunKey, RunValueName);
  RegDeleteValue(HKLM, RunKey, RunValueName);

  if UninstallSilent then
    Exit;

  if MsgBox('是否同时删除已保存的账号配置和运行日志？' + #13#10 + #13#10 +
            ExpandConstant('{userappdata}\NJUPT_NET'), mbConfirmation, MB_YESNO) = IDYES then
  begin
    DelTree(ExpandConstant('{userappdata}\NJUPT_NET'), True, True, True);
  end;
end;
