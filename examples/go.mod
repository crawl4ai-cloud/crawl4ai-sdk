// The Go examples. The replace line runs them against the SDK in this repository; outside it,
// `go get github.com/crawl4ai-cloud/crawl4ai-sdk/go` is enough.
module github.com/crawl4ai-cloud/crawl4ai-sdk/examples

go 1.23

require github.com/crawl4ai-cloud/crawl4ai-sdk/go v1.0.0

replace github.com/crawl4ai-cloud/crawl4ai-sdk/go => ../go
