/**
 * JobService triggered by content://mms provider updates or scan requests.
 * Runs MmsScanner to process newly arrived inbox MMS messages.
 *
 * Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
 */
// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
package org.ps3.sentinel.sms

import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.concurrent.Executors

class MmsWatchJobService : JobService() {
    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var active: CancellationSignal? = null

    override fun onStartJob(params: JobParameters): Boolean {
        if (!MmsWatcher.allowed(this)) {
            MmsWatcher.cancel(this)
            return false
        }
        if (params.jobId == MmsWatcher.JOB_ID) {
            MmsWatcher.requestScan(this)
            try {
                MmsWatcher.arm(this)
            } catch (_: Exception) {
                Log.w(TAG, "mms_trigger_unscheduled")
            }
            return false
        }
        val signal = CancellationSignal()
        val generation = MmsWatcher.begin(this, signal) ?: return false
        active = signal
        executor.execute {
            val retry = try {
                if (requireNotNull(getSystemService(JobScheduler::class.java)).getPendingJob(MmsWatcher.JOB_ID) == null) {
                    MmsWatcher.arm(this)
                }
                MmsWatcher.scan(this, signal, generation)
            } catch (_: Exception) {
                if (!signal.isCanceled) Log.w(TAG, "mms_scan_failed")
                true
            }
            main.post {
                if (active === signal) {
                    active = null
                    MmsWatcher.end(signal)
                    jobFinished(params, retry && MmsWatcher.allowed(this))
                }
            }
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        if (params.jobId == MmsWatcher.SCAN_JOB_ID) stopScan()
        return MmsWatcher.allowed(this)
    }

    override fun onDestroy() {
        stopScan()
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun stopScan() {
        active?.let {
            it.cancel()
            MmsWatcher.end(it)
        }
        active = null
    }

    private companion object {
        const val TAG = "PS3Mms"
    }
}
