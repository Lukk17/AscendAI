SIGN_IN_HTML = (
    "<html><head><title>Sign in</title></head><body><main><h1>Sign in to your account</h1>"
    "<p>Welcome back. Enter the email address you use for your account and we will take you"
    ' to the next step.</p><form action="/session"><label>Email address</label>'
    '<input type="email" name="email"><button type="submit">Next</button></form>'
    "</main></body></html>"
)

_LOGIN_ARTICLE_PARAGRAPHS = (
    "In computer security, logging in is the process by which a person gains access to a computer"
    " system by identifying and authenticating themselves. The credentials are usually a username"
    " and a matching password, and together they are often called a login.",
    "Logging in is usually needed to reach a private page, and the person stays logged in until"
    " they log out or the session expires. Many systems record every login with the time and the"
    " address it came from, so an administrator can review who used an account and when.",
    "The term became common in the nineteen sixties with the rise of time sharing systems, where"
    " many users shared one large machine through terminals. Each user had to announce themselves"
    " to the system before it would accept any command from that terminal.",
    "Modern websites often offer a single sign on, which lets one login open several related"
    " services. Others add a second factor, such as a code sent to a phone or a hardware key,"
    " because a stolen password alone is then no longer enough to enter the account.",
    "Security advice recommends a long and unique password for every service, a password manager"
    " to remember them, and a second factor wherever a site supports one. Phishing pages copy a"
    " real login screen to steal credentials, so users should check the address before typing.",
)

WIKIPEDIA_LOGIN_ARTICLE_HTML = (
    "<html><head><title>Login - Wikipedia</title></head><body>"
    '<header><a href="/w/index.php?title=Special:UserLogin">Log in</a>'
    '<form action="/w/index.php?title=Special:UserLogin"><input type="text" name="wpName">'
    '<input type="password" name="wpPassword"><button type="submit">Log in</button></form></header>'
    "<main><article><h1>Login</h1>"
    + "".join(f"<p>{paragraph}</p>" for paragraph in _LOGIN_ARTICLE_PARAGRAPHS)
    + "</article></main></body></html>"
)
