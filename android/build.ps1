param([string]$Sdk = '', [string]$Jdk = 'D:/Program Files/Java/jdk1.8.0_301')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
if (-not $Sdk) { $Sdk = Join-Path $project 'build/android-tools' }
$tools = Join-Path $Sdk 'android-11'
$platform = Join-Path $Sdk 'android-11/android.jar'
$output = Join-Path $project 'dist-android'
$compiled = Join-Path $project 'build/android-package'
New-Item -ItemType Directory -Force $output,"$compiled/classes","$compiled/dex","$compiled/generated","$compiled/check" | Out-Null
function Invoke-Checked([string]$exe,[string[]]$arguments) { & $exe @arguments; if ($LASTEXITCODE -ne 0) { throw "Failed: $exe ($LASTEXITCODE)" } }
$java = Join-Path $Jdk 'bin/java.exe'
$javac = Join-Path $Jdk 'bin/javac.exe'
Invoke-Checked $javac @('-encoding','UTF-8','-d',"$compiled/check","$PSScriptRoot/src/cn/infra/researcher/companion/AddressPolicy.java","$PSScriptRoot/AddressPolicyCheck.java")
Invoke-Checked $java @('-cp',"$compiled/check",'cn.infra.researcher.companion.AddressPolicyCheck')
Push-Location $project
try { Invoke-Checked "$tools/aapt.exe" @('package','-f','-m','-J','build/android-package/generated','-M','android/AndroidManifest.xml','-S','android/res','-I','build/android-tools/android-11/android.jar','-F','build/android-package/unsigned.apk') } finally { Pop-Location }
$sources = @(Get-ChildItem "$PSScriptRoot/src","$compiled/generated" -Filter '*.java' -Recurse | ForEach-Object FullName)
Invoke-Checked $javac (@('-encoding','UTF-8','-source','8','-target','8','-bootclasspath',$platform,'-classpath',"$tools/core-lambda-stubs.jar",'-d',"$compiled/classes") + $sources)
Invoke-Checked (Join-Path $Jdk 'bin/jar.exe') @('cf',"$compiled/classes.jar",'-C',"$compiled/classes",'.')
Invoke-Checked $java @('-cp',"$tools/lib/d8.jar",'com.android.tools.r8.D8','--lib',$platform,'--min-api','23','--output',"$compiled/dex","$compiled/classes.jar")
Push-Location "$compiled/dex"
try { Invoke-Checked "$tools/aapt.exe" @('add','../unsigned.apk','classes.dex') } finally { Pop-Location }
Push-Location $project
try { Invoke-Checked "$tools/zipalign.exe" @('-f','4','build/android-package/unsigned.apk','build/android-package/aligned.apk') } finally { Pop-Location }
# Local development signing key, retained for installing updates over this build.
$key = Join-Path $compiled 'companion-dev.jks'
if (-not (Test-Path -LiteralPath $key)) {
    Invoke-Checked (Join-Path $Jdk 'bin/keytool.exe') @('-genkeypair','-keystore',$key,'-storepass','android','-keypass','android','-alias','companion-dev','-dname','CN=Infra Researcher Local Development','-keyalg','RSA','-keysize','2048','-validity','10000')
}
$apk = Join-Path $output 'InfraResearcher-Android.apk'
Invoke-Checked $java @('-jar',"$tools/lib/apksigner.jar",'sign','--ks',$key,'--ks-pass','pass:android','--key-pass','pass:android','--ks-key-alias','companion-dev','--out',$apk,"$compiled/aligned.apk")
Invoke-Checked $java @('-jar',"$tools/lib/apksigner.jar",'verify','--verbose','--print-certs',$apk)
Push-Location $project
try { Invoke-Checked "$tools/aapt.exe" @('dump','badging','dist-android/InfraResearcher-Android.apk') } finally { Pop-Location }
Get-FileHash -LiteralPath $apk -Algorithm SHA256 | Format-List
Write-Output "APK: $apk"
