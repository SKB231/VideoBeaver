package models

// VideoStream contains metadata for a single video stream
type VideoStream struct {
	Index         int      `json:"index"`
	CodecName     string   `json:"codec_name"`
	CodecLongName string   `json:"codec_long_name,omitempty"`
	Width         int      `json:"width"`
	Height        int      `json:"height"`
	Duration      *float64 `json:"duration_seconds,omitempty"`
	BitRate       *int64   `json:"bit_rate,omitempty"` // bits per second
	FrameRate     string   `json:"frame_rate,omitempty"`
	PixFmt        string   `json:"pix_fmt,omitempty"`
}

// AudioStream contains metadata for a single audio stream
type AudioStream struct {
	Index         int      `json:"index"`
	CodecName     string   `json:"codec_name"`
	CodecLongName string   `json:"codec_long_name,omitempty"`
	SampleRate    *int     `json:"sample_rate,omitempty"`
	Channels      *int     `json:"channels,omitempty"`
	BitRate       *int64   `json:"bit_rate,omitempty"`
	Duration      *float64 `json:"duration_seconds,omitempty"`
}

// VideoMetadata contains complete metadata extracted from ffprobe
type VideoMetadata struct {
	Filename       string        `json:"filename"`
	FormatName     string        `json:"format_name"`
	FormatLongName string        `json:"format_long_name,omitempty"`
	Duration       float64       `json:"duration_seconds"`
	SizeBytes      int64         `json:"size_bytes"`
	BitRate        int64         `json:"bit_rate"` // overall bitrate in bits per second
	VideoStreams   []VideoStream `json:"video_streams"`
	AudioStreams   []AudioStream `json:"audio_streams"`
}

// ProbeResult is the result sent back after probing a video
type ProbeResult struct {
	JobID    string         `json:"job_id"`
	S3Key    string         `json:"s3_key"`
	Status   string         `json:"status"` // "completed" or "failed"
	Metadata *VideoMetadata `json:"metadata,omitempty"`
	Error    string         `json:"error,omitempty"`
}

// CompressResult is the result sent back after compressing a video
type CompressResult struct {
	JobID       string `json:"job_id"`
	Status      string `json:"status"` // "completed" or "failed"
	OutputS3Key string `json:"output_s3_key,omitempty"`
	OutputURL   string `json:"output_url,omitempty"` // presigned download URL
	Error       string `json:"error,omitempty"`
}
