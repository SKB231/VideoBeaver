import { useState, useEffect } from 'react'
import './App.css'

const CODECS = [
  { value: 'h264', label: 'H.264 (Most Compatible)' },
  { value: 'h265', label: 'H.265/HEVC (Better Compression)' },
  { value: 'vp9', label: 'VP9 (Web Optimized)' },
  { value: 'av1', label: 'AV1 (Best Compression, Slow)' },
]

const CONTAINERS = [
  { value: 'mp4', label: 'MP4' },
  { value: 'webm', label: 'WebM' },
  { value: 'mkv', label: 'MKV' },
  { value: 'mov', label: 'MOV' },
]

function uploadToS3(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => resolve(xhr.status)
    xhr.onerror = () => reject(new Error('Network error during S3 upload.'))
    xhr.send(formData)
  })
}

function formatDuration(seconds) {
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  if (hrs > 0) return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function formatBitrate(bps) {
  if (!bps) return 'N/A'
  const kbps = bps / 1000
  if (kbps >= 1000) return `${(kbps / 1000).toFixed(1)} Mbps`
  return `${Math.round(kbps)} kbps`
}

function formatFileSize(bytes) {
  if (!bytes) return 'N/A'
  const mb = bytes / (1024 * 1024)
  if (mb >= 1000) return `${(mb / 1024).toFixed(2)} GB`
  return `${mb.toFixed(2)} MB`
}

function App() {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')
  const [s3Key, setS3Key] = useState(null)

  // Job tracking
  const [probeJobId, setProbeJobId] = useState(null)
  const [compressJobId, setCompressJobId] = useState(null)
  const [metadata, setMetadata] = useState(null)
  const [compressResult, setCompressResult] = useState(null)

  // Compression options
  const [codec, setCodec] = useState('h264')
  const [container, setContainer] = useState('mp4')
  const [maxBitrate, setMaxBitrate] = useState('')
  const [keepAudio, setKeepAudio] = useState(true)

  // Poll for job status
  useEffect(() => {
    if (!probeJobId || metadata) return

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/jobs/${probeJobId}`)
        const data = await response.json()

        if (data.status === 'completed' && data.metadata) {
          setMetadata(data.metadata)
          setStatus('analyzed')
          clearInterval(interval)
        } else if (data.status === 'failed') {
          setErrorMsg(data.error || 'Analysis failed')
          setStatus('error')
          clearInterval(interval)
        }
      } catch (err) {
        console.error('Error polling probe status:', err)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [probeJobId, metadata])

  // Poll for compression job status
  useEffect(() => {
    if (!compressJobId || compressResult) return

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/jobs/${compressJobId}`)
        const data = await response.json()

        if (data.status === 'completed') {
          setCompressResult(data)
          setStatus('compressed')
          clearInterval(interval)
        } else if (data.status === 'failed') {
          setErrorMsg(data.error || 'Compression failed')
          setStatus('error')
          clearInterval(interval)
        }
      } catch (err) {
        console.error('Error polling compress status:', err)
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [compressJobId, compressResult])

  const onFileSelect = (event) => {
    const picked = event.target.files[0]
    if (!picked) return
    setFile(picked)
    setStatus('selected')
    setProgress(0)
    setErrorMsg('')
    setMetadata(null)
    setProbeJobId(null)
    setCompressJobId(null)
    setCompressResult(null)
    setS3Key(null)
  }

  const onUpload = async () => {
    if (!file) return

    setStatus('uploading')
    setProgress(0)
    setErrorMsg('')

    // Phase 1 - get presigned POST URL
    let url, fields
    try {
      const response = await fetch('/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, file_size: file.size }),
      })

      if (!response.ok) {
        const err = await response.json()
        setErrorMsg(err.detail || 'Failed to get upload URL.')
        setStatus('error')
        return
      }

      ;({ url, fields } = await response.json())
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('error')
      return
    }

    // Phase 2 - upload to S3
    const formData = new FormData()
    Object.entries(fields).forEach(([k, v]) => formData.append(k, v))
    formData.append('file', file)

    try {
      const statusCode = await uploadToS3(url, formData, setProgress)
      if (statusCode !== 204 && statusCode !== 200) {
        setErrorMsg(`Upload to S3 failed (status ${statusCode}).`)
        setStatus('error')
        return
      }
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('error')
      return
    }

    setS3Key(fields.key)

    // Phase 3 - queue analysis
    setStatus('analyzing')
    try {
      const response = await fetch('/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ s3_key: fields.key, s3_url: url }),
      })

      if (!response.ok) {
        const err = await response.json()
        setErrorMsg(err.detail || 'Analysis request failed.')
        setStatus('error')
        return
      }

      const data = await response.json()
      setProbeJobId(data.job_id)
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('error')
    }
  }

  const onCompress = async () => {
    if (!s3Key) return

    setStatus('compressing')
    setErrorMsg('')
    setCompressResult(null)

    try {
      const response = await fetch('/compress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          s3_key: s3Key,
          video_codec: codec,
          container: container,
          max_bitrate_kbps: maxBitrate ? parseInt(maxBitrate) : null,
          keep_audio: keepAudio,
        }),
      })

      if (!response.ok) {
        const err = await response.json()
        setErrorMsg(err.detail || 'Compression request failed.')
        setStatus('error')
        return
      }

      const data = await response.json()
      setCompressJobId(data.job_id)
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('error')
    }
  }

  const busy = status === 'uploading' || status === 'analyzing' || status === 'compressing'

  return (
    <div id="container">
      <h1>videoBeaver</h1>

      {/* File Selection */}
      <section className="section">
        <p>Select a video file to upload.</p>
        <input type="file" accept="video/*" onChange={onFileSelect} disabled={busy} />
        {file && status === 'selected' && (
          <button onClick={onUpload}>Upload</button>
        )}
      </section>

      {/* Progress */}
      {status === 'uploading' && (
        <section className="section">
          <div id="progress-bar-track">
            <div id="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>
          <p className="status">Uploading... {progress}%</p>
        </section>
      )}

      {status === 'analyzing' && <p className="status">Analyzing video...</p>}

      {/* Metadata Display */}
      {metadata && (
        <section className="section metadata">
          <h2>Video Information</h2>
          <div className="metadata-grid">
            <div className="metadata-item">
              <span className="label">Duration</span>
              <span className="value">{formatDuration(metadata.duration_seconds)}</span>
            </div>
            <div className="metadata-item">
              <span className="label">File Size</span>
              <span className="value">{formatFileSize(metadata.size_bytes)}</span>
            </div>
            <div className="metadata-item">
              <span className="label">Bitrate</span>
              <span className="value">{formatBitrate(metadata.bit_rate)}</span>
            </div>
            <div className="metadata-item">
              <span className="label">Format</span>
              <span className="value">{metadata.format_name}</span>
            </div>
          </div>

          {metadata.video_streams?.length > 0 && (
            <>
              <h3>Video Streams</h3>
              {metadata.video_streams.map((stream, i) => (
                <div key={i} className="stream-info">
                  <span>{stream.width}x{stream.height}</span>
                  <span>{stream.codec_name}</span>
                  <span>{stream.frame_rate}</span>
                  <span>{formatBitrate(stream.bit_rate)}</span>
                </div>
              ))}
            </>
          )}

          {metadata.audio_streams?.length > 0 && (
            <>
              <h3>Audio Streams</h3>
              {metadata.audio_streams.map((stream, i) => (
                <div key={i} className="stream-info">
                  <span>{stream.codec_name}</span>
                  <span>{stream.channels}ch</span>
                  <span>{stream.sample_rate ? `${stream.sample_rate}Hz` : ''}</span>
                  <span>{formatBitrate(stream.bit_rate)}</span>
                </div>
              ))}
            </>
          )}
        </section>
      )}

      {/* Compression Options */}
      {metadata && status === 'analyzed' && (
        <section className="section options">
          <h2>Compression Options</h2>

          <div className="option-group">
            <label htmlFor="codec">Video Codec</label>
            <select id="codec" value={codec} onChange={(e) => setCodec(e.target.value)}>
              {CODECS.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>

          <div className="option-group">
            <label htmlFor="container">Container</label>
            <select id="container" value={container} onChange={(e) => setContainer(e.target.value)}>
              {CONTAINERS.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>

          <div className="option-group">
            <label htmlFor="bitrate">Max Bitrate (kbps)</label>
            <input
              id="bitrate"
              type="number"
              placeholder="Leave empty for auto"
              value={maxBitrate}
              onChange={(e) => setMaxBitrate(e.target.value)}
            />
          </div>

          <div className="option-group checkbox">
            <input
              id="keepAudio"
              type="checkbox"
              checked={keepAudio}
              onChange={(e) => setKeepAudio(e.target.checked)}
            />
            <label htmlFor="keepAudio">Keep Audio Track</label>
          </div>

          <button className="compress-btn" onClick={onCompress}>
            Compress Video
          </button>
        </section>
      )}

      {/* Compression Progress */}
      {status === 'compressing' && (
        <p className="status">Compressing video... This may take a while.</p>
      )}

      {/* Compression Result */}
      {compressResult && status === 'compressed' && (
        <section className="section result">
          <h2>Compression Complete</h2>
          <p>Output: {compressResult.output_s3_key}</p>
          {compressResult.output_url && (
            <a href={compressResult.output_url} className="download-btn" download>
              Download Compressed Video
            </a>
          )}
        </section>
      )}

      {/* Error */}
      {status === 'error' && <p className="status error">{errorMsg}</p>}
    </div>
  )
}

export default App
