export interface FeedbackState {
  error: string;
  success: string;
}

export function beginFeedback(state: FeedbackState): void {
  state.error = "";
  state.success = "";
}

export function setFeedbackSuccess(state: FeedbackState, message: string): void {
  state.error = "";
  state.success = message;
}

export function setFeedbackError(state: FeedbackState, message: string): void {
  state.success = "";
  state.error = message;
}
