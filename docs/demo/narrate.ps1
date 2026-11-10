# Écrit un WAV par temps du scénario (docs/demo/voice/NN.wav) avec la voix française installée, et donne leur durée.
Add-Type -AssemblyName System.Speech
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sc = Get-Content -Raw -Encoding UTF8 (Join-Path $here 'scenario.json') | ConvertFrom-Json
$out = Join-Path $here 'voice'
New-Item -ItemType Directory -Force $out | Out-Null
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Hortense Desktop')
$s.Rate = -1
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(44100, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$total = 0.0
for ($i = 0; $i -lt $sc.beats.Count; $i++) {
    $f = Join-Path $out ('{0:00}.wav' -f $i)
    $s.SetOutputToWaveFile($f, $fmt)
    $s.Speak($sc.beats[$i].say)
    $s.SetOutputToNull()
    $d = ((Get-Item $f).Length - 44) / 88200.0
    $total += $d
    '{0:00}.wav  {1:N1} s' -f $i, $d
}
'total {0:N1} s' -f $total
