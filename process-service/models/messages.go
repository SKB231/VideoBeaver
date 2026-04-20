package models

// MessageType identifies the type of SQS message
type MessageType string

const (
	MessageTypeProbe    MessageType = "probe"
	MessageTypeCompress MessageType = "compress"
)

// VideoCodec represents supported video codecs
type VideoCodec string

const (
	CodecH264 VideoCodec = "h264"
	CodecH265 VideoCodec = "h265"
	CodecVP9  VideoCodec = "vp9"
	CodecAV1  VideoCodec = "av1"
)

// Container represents supported container formats
type Container string

const (
	ContainerMP4  Container = "mp4"
	ContainerWebM Container = "webm"
	ContainerMKV  Container = "mkv"
	ContainerMOV  Container = "mov"
)

// BaseMessage contains common fields for all SQS messages
type BaseMessage struct {
	MessageType MessageType `json:"message_type"`
	JobID       string      `json:"job_id"`
	S3Bucket    string      `json:"s3_bucket"`
	S3Key       string      `json:"s3_key"`
	CallbackURL string      `json:"callback_url,omitempty"`
}

// ProbeMessage is the SQS message payload for video probe requests
type ProbeMessage struct {
	BaseMessage
}

// CompressMessage is the SQS message payload for video compression requests
type CompressMessage struct {
	BaseMessage
	VideoCodec     VideoCodec `json:"video_codec"`
	Container      Container  `json:"container"`
	MaxBitrateKbps *int       `json:"max_bitrate_kbps,omitempty"` // nil = no limit
	KeepAudio      bool       `json:"keep_audio"`
	OutputS3Bucket string     `json:"output_s3_bucket,omitempty"` // defaults to input bucket
	OutputS3Key    string     `json:"output_s3_key,omitempty"`    // defaults to auto-generated
}

// SQSMessageWrapper wraps the raw SQS message for initial parsing
type SQSMessageWrapper struct {
	MessageType MessageType `json:"message_type"`
}
