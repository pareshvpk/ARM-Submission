#!/system/bin/sh
# On-device offline proof for PS3 Sentinel (runs detached on the phone, survives
# the wireless-adb drop caused by airplane mode).
# Push to /data/local/tmp and start with:
#   adb shell "nohup sh /data/local/tmp/offline_run.sh > /data/local/tmp/offline_run.log 2>&1 &"
# Note: /system/bin/sh on Android is mksh, which supports `set -eu` but NOT `set -o pipefail`;
# pipefail is therefore emulated by checking $? after each critical pipeline step.
set -eu
OUT=/data/local/tmp/ps3_offline
TAP_X="${TAP_X:-540}"
TAP_MSG_Y="${TAP_MSG_Y:-540}"
TAP_ANALYSE_Y="${TAP_ANALYSE_Y:-780}"
log() { echo "$@"; }
mkdir -p "$OUT"
# Ensure every exit path (normal completion, explicit exit, or a set -e failure)
# restores connectivity and stops the recording: mksh supports `trap ... EXIT`.
# The trap must never delete $OUT: the screenshots and recording in it are the
# evidence the host pulls afterwards, and they must survive early exits too.
# Deleting the phone-side folder is the host's job, after it has pulled it.
restore_airplane() {
  cmd connectivity airplane-mode disable 2>/dev/null || true
  if [ -n "${REC:-}" ]; then
    kill -2 "$REC" 2>/dev/null || true
  fi
}
trap 'restore_airplane' EXIT
log "start, model $(getprop ro.product.model), android $(getprop ro.build.version.release)"
screenrecord --time-limit 170 "$OUT/offline_run.mp4" &
REC=$!
sleep 2

cmd connectivity airplane-mode enable
sleep 6
log "airplane_mode_on=$(settings get global airplane_mode_on)"
if ping -c 2 -W 2 8.8.8.8 >/dev/null 2>&1; then
  echo "FAIL: network still reachable after airplane mode (ping 8.8.8.8 succeeded); aborting" >&2
  log "NETWORK: UP (test invalid) - aborting"
  kill -2 "$REC" 2>/dev/null || true
  cmd connectivity airplane-mode disable
  exit 1
fi
log "NETWORK: DOWN (offline, as intended)"
ip -br addr 2>/dev/null || ip addr | grep -E "^[0-9]+:|inet " || true

# Tap the centre of a view by resource id (activity_main.xml), falling back
# to the given fixed coordinates when the uiautomator lookup fails.
# Usage: tap_view etMessage "$TAP_X" "$TAP_MSG_Y"
tap_view() {
  _tv_id=$1; _tv_fx=$2; _tv_fy=$3
  uiautomator dump >/dev/null 2>&1 || true
  _tv_line=$(grep "resource-id=\"org.ps3.sentinel:id/$_tv_id\"" /sdcard/window_dump.xml 2>/dev/null | head -n 1)
  _tv_n=$(printf '%s' "$_tv_line" | sed -n 's/.*bounds="\[([0-9]*),([0-9]*)\]\[([0-9]*),([0-9]*)\]".*/\1 \2 \3 \4/p')
  if [ -n "$_tv_n" ]; then
    set -- $_tv_n
    _tv_x=$(( ($1 + $3) / 2 )); _tv_y=$(( ($2 + $4) / 2 ))
    log "tap $_tv_id via uiautomator ($_tv_x,$_tv_y)"
    input tap "$_tv_x" "$_tv_y"
  else
    log "tap $_tv_id via fallback ($_tv_fx,$_tv_fy)"
    input tap "$_tv_fx" "$_tv_fy"
  fi
}
run_msg() {
  n=$1; text=$2; wait=$3
  am start -n org.ps3.sentinel/.ui.MainActivity >/dev/null 2>&1
  sleep 2
  tap_view etMessage "$TAP_X" "$TAP_MSG_Y"
  input keycombination 113 29
  input keyevent 67
  input text "$text"
  tap_view btnAnalyse "$TAP_X" "$TAP_ANALYSE_Y"
  sleep 1
  dumpsys input_method | grep -q "mInputShown=true" && input keyevent 4 || true
  log "msg $n analysing"
  sleep $wait
  input swipe 540 1800 540 700 400
  sleep 1
  screencap -p "$OUT/offline_msg_$n.png"
  input swipe 540 700 540 1800 300
  log "msg $n screenshot saved"
}

run_msg 1 'Dear%scustomer%syour%sSBI%saccount%sKYC%sis%spending,%saccount%swill%sbe%sblocked%stoday.%sUpdate%snow:%shttp://sbi-kyc-update.xyz/login' 30
run_msg 2 'Aapka%sbijli%sconnection%saaj%sraat%s9%sbaje%skat%sjayega,%sturant%sofficer%sko%s9876543210%scall%skarein' 30
run_msg 3 'Your%sOTP%sfor%sHDFC%sNetBanking%sis%s482910.%sValid%sfor%s5%smins.%sDo%snot%sshare%sit%swith%sanyone.' 6

log "airplane_mode_on=$(settings get global airplane_mode_on) before restore"
kill -2 "$REC" 2>/dev/null || true
sleep 3
cmd connectivity airplane-mode disable
log "done, airplane mode off; evidence kept in $OUT for the host to pull (host deletes $OUT after pulling)"
