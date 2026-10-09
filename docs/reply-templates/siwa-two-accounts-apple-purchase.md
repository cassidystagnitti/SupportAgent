# Reply template — two accounts from Sign in with Apple / Hide My Email + an Apple purchase

**Use when (solo, decision 2026-10-09 — Amy Friese #322015, approved by Cassidy):** the customer paid on one account (usually Stripe/web on their real email) and ALSO has an Apple App Store charge on a second account that was created by Sign in with Apple, often with a Hide My Email `…@privaterelay.appleid.com` relay address. They're confused about the double charge or which account is which.

**Before sending:** add both emails (incl. the relay) to the Help Scout profile; confirm in admin/Maven which account holds which subscription and the dates/amounts; confirm the web sub is active. We can't refund the Apple charge. Don't mention next year's renewal price. If the Stripe/web side is the one they want refunded and it's in-window, that's a separate solo refund (*Refund Policy*). Fill every `{…}`; drop optional bits in braces that don't apply.

Policy: `policies/login-issues.md` → *Two accounts from Sign in with Apple / Hide My Email*.

---

Hi {first},

Thank you for {the screenshot / the details}. It helped us figure out what happened! You actually have two Happier Meditation accounts.

How it happened
On {date}, you subscribed on our website{ with the 40% offer} on your {email} account and paid {web price}. {A few minutes later / Later}, you were signed in to the iPhone app with Sign in with Apple. That created a second, separate account, and buying in the app charged your Apple ID {apple price}.

What Sign in with Apple and Hide My Email are
Sign in with Apple lets you sign in to apps with your Apple ID instead of an email and password. When you use it, Apple can also turn on Hide My Email. That creates a random private address (like ...@privaterelay.appleid.com) that forwards to your real email, so the app never sees your real address. That's why your second account doesn't show your {Gmail} address.

Getting the {apple price} refunded
Apple handles App Store charges, so the refund request has to come from you:
- Go to reportaproblem.apple.com and sign in with your Apple ID, or open Apple's receipt email and tap Report a Problem.
- Choose Request a refund and pick a reason, like "I didn't mean to buy this."
- Apple makes the decision, usually within a few days.

Turning off the Apple subscription
So it doesn't renew, on your iPhone go to Settings → [your name] → Subscriptions → Happier Meditation → Cancel Subscription.

Using your {web price} membership
In the app, sign out, then sign back in with {email} using your email and password (not Sign in with Apple). If you don't remember your password, tap Forgot Password on the sign-in screen.

Your {web price} membership on {email} stays active, so you won't lose anything.

Take care,
Happier Meditation Support Team
