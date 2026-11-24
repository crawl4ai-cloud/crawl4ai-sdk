package crawl4ai

import (
	"errors"
	"fmt"
)

// The kinds of error. Test for one with errors.Is:
//
//	if errors.Is(err, crawl4ai.ErrPaymentRequired) { ... }
var (
	ErrBadRequest      = errors.New("bad request")      // 400 or 422: a field is wrong
	ErrAuthentication  = errors.New("authentication")   // 401: no key, or a key that is not valid
	ErrPaymentRequired = errors.New("payment required") // 402: out of credit
	ErrBlocked         = errors.New("blocked")          // 403: the site refused every attempt
	ErrNotFound        = errors.New("not found")        // 404: no such job, or not open to this account
	ErrRateLimit       = errors.New("rate limit")       // 429: over the plan's pace, after every retry
	ErrServer          = errors.New("server error")     // 5xx: the service or the site failed
	ErrConnection      = errors.New("connection")       // no answer came back
	ErrTimeout         = errors.New("timeout")          // no answer in time; it is also an ErrConnection
)

var errorKinds = map[int]error{
	400: ErrBadRequest,
	401: ErrAuthentication,
	402: ErrPaymentRequired,
	403: ErrBlocked,
	404: ErrNotFound,
	422: ErrBadRequest,
	429: ErrRateLimit,
}

// Error is every error the client returns.
//
// Kind is one of the Err values above (nil for a status without one), Status the HTTP status (0
// when no answer came back), Code the server's short code (`no_credit`, `blocked`, ...), Message
// text you can show to people as it is, Actions the server's links that fix the problem (for
// example `subscribe`), and Body the whole error answer (Body["did_you_mean"] lists the closest
// tool ids on a 404 `tool_not_found`). Err is the cause, for example context.Canceled.
//
//	var e *crawl4ai.Error
//	if errors.As(err, &e) { fmt.Println(e.Status, e.Code, e.Message) }
type Error struct {
	Kind    error
	Status  int
	Code    string
	Message string
	Actions map[string]any
	Body    map[string]any
	Err     error
}

func (e *Error) Error() string {
	if e.Status != 0 {
		return fmt.Sprintf("crawl4ai: %d: %s", e.Status, e.Message)
	}
	return "crawl4ai: " + e.Message
}

// Is reports whether the error is of the kind `target`.
func (e *Error) Is(target error) bool {
	return target != nil && (target == e.Kind || (e.Kind == ErrTimeout && target == ErrConnection))
}

func (e *Error) Unwrap() error { return e.Err }
