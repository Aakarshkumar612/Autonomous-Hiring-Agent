/**
 * lib/errors.ts
 * Converts raw technical errors into friendly messages safe to show any user.
 * Never expose: stack traces, server commands, HTTP status codes, or internal paths.
 */

import { ApiError } from './api'

export function friendlyError(err: unknown): string {
  // Known API errors with HTTP status codes
  if (err instanceof ApiError) {
    switch (err.statusCode) {
      case 400: return 'The request could not be processed. Please check your inputs and try again.'
      case 401: return 'You are not authorised to perform this action. Please sign in again.'
      case 403: return 'You do not have permission to access this resource.'
      case 404: return 'The requested data could not be found.'
      case 409: return 'A conflict occurred. This record may already exist.'
      case 413: return 'The file is too large. Please upload a smaller file (max 10 MB).'
      case 415: return 'This file type is not supported. Please upload a PDF, DOCX, CSV, or Excel file.'
      case 422: return 'Some of the information submitted is invalid. Please review your inputs.'
      case 429: return 'Too many requests. Please wait a moment and try again.'
      case 503: return 'The service is temporarily unavailable. Please try again shortly.'
      default:  return 'Something went wrong on our end. Please try again.'
    }
  }

  // Network / fetch errors (backend offline, CORS, DNS failure)
  if (err instanceof Error) {
    const msg = err.message.toLowerCase()
    if (
      msg.includes('network') ||
      msg.includes('fetch') ||
      msg.includes('econnrefused') ||
      msg.includes('failed to fetch') ||
      msg.includes('offline')
    ) {
      return 'Unable to connect to the server. Please check your internet connection and try again.'
    }
  }

  // Fallback — never show raw error details
  return 'Something went wrong. Please try again.'
}
