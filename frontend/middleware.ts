import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

/**
 * Route protection strategy:
 *
 * - /dashboard and everything under it → PROTECTED (must be signed in)
 * - / (landing), /sign-in, /sign-up   → PUBLIC (no auth needed)
 *
 * How it works:
 * 1. Every request hits this middleware FIRST, before any page code runs.
 * 2. If the route is protected and the user has no valid Clerk session,
 *    they are redirected to /sign-in automatically.
 * 3. If they are signed in, the request passes through unchanged.
 *
 * Note: In @clerk/nextjs v5.7+, auth is a callable function — you must
 * call auth() first to get the session state, then check userId.
 */

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)'])

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    const { userId } = await auth()
    if (!userId) {
      const signInUrl = new URL('/sign-in', req.url)
      return NextResponse.redirect(signInUrl)
    }
  }
})

export const config = {
  // Run middleware on all routes except static files and Next.js internals.
  matcher: ['/((?!.*\\..*|_next).*)', '/', '/(api|trpc)(.*)'],
}
