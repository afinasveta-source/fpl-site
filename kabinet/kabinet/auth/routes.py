from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .schemas import EmailInput, Login, SetPassword, SessionView, UserView

router = APIRouter(prefix='/auth', tags=['auth'])
bearer = HTTPBearer(auto_error=False)


def service(request: Request):
    return request.app.state.auth


def credentials(value: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not value or value.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    return value.credentials


def current_user(raw=Depends(credentials), auth=Depends(service)):
    return auth.current_user(raw)


def admin(user=Depends(current_user)):
    if 'admin' not in user['roles']:
        raise HTTPException(403, 'Administrator role required')
    return user


def client_ip(request):
    # Forwarded headers are intentionally ignored here; trust proxy only at deployment boundary.
    return request.client.host if request.client else 'unknown'


@router.post('/login', response_model=SessionView)
def login(body: Login, request: Request, auth=Depends(service)):
    return auth.login(body.email, body.password, client_ip(request))


@router.get('/me', response_model=UserView)
def me(user=Depends(current_user)):
    return user


@router.post('/logout', status_code=204)
def logout(raw=Depends(credentials), auth=Depends(service)):
    auth.logout(raw)
    return Response(status_code=204)


@router.post('/password/reset-request', status_code=202)
def request_reset(body: EmailInput, request: Request, tasks: BackgroundTasks, auth=Depends(service)):
    auth.throttle('reset', client_ip(request), body.email)
    tasks.add_task(auth.request_reset, body.email)
    return {'message': 'If the account is eligible, an email will be sent'}


@router.post('/password/set', status_code=204)
def set_password(body: SetPassword, request: Request, auth=Depends(service)):
    auth.throttle('consume', client_ip(request))
    auth.consume_token(body.token, body.password, 'set_password')
    return Response(status_code=204)


@router.post('/password/reset', status_code=204)
def reset_password(body: SetPassword, request: Request, auth=Depends(service)):
    auth.throttle('consume', client_ip(request))
    auth.consume_token(body.token, body.password, 'reset_password')
    return Response(status_code=204)
