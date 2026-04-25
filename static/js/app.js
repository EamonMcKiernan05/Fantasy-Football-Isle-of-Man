/** Fantasy Football Isle of Man - Frontend Application */

// State
const state = {
    user: JSON.parse(localStorage.getItem('ff_iom_user') || 'null'),
    teams: [],
    divisions: [],
    gameweeks: [],
    leaderboard: [],
};

// API helpers
async function api(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : endpoint;
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
    };
    
    const resp = await fetch(url, { ...defaults, ...options });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

// Navigation
function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    
    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');
    
    const link = document.querySelector(`.nav-link[data-page="${page}"]`);
    if (link) link.classList.add('active');
    
    // Load page data
    switch(page) {
        case 'teams': loadTeams(); break;
        case 'my-team': loadMyTeam(); break;
        case 'leaderboard': loadLeaderboard(); break;
        case 'gameweeks': loadGameweeks(); break;
    }
}

// Nav link clicks
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        showPage(link.dataset.page);
    });
});

// Toast notifications
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container') || (() => {
        const div = document.createElement('div');
        div.id = 'toast-container';
        div.className = 'toast-container';
        document.body.appendChild(div);
        return div;
    })();
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => toast.remove(), 3000);
}

// Auth
async function handleRegister(e) {
    e.preventDefault();
    
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const teamName = document.getElementById('reg-team-name').value;
    
    try {
        const user = await api('/api/users/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password }),
        });
        
        // Create fantasy team
        await api(`/api/users/${user.id}/team/create`, {
            method: 'POST',
            body: JSON.stringify({ team_name: teamName }),
        });
        
        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        updateNav();
        showToast(`Welcome ${username}! Your team "${teamName}" has been created.`);
        showPage('my-team');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function handleLogin(e) {
    e.preventDefault();
    
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    
    // Simple login - check against stored users
    const stored = JSON.parse(localStorage.getItem('ff_iom_users') || '[]');
    const user = stored.find(u => u.username === username && u.password === password);
    
    if (user) {
        state.user = { id: user.id, username: user.username, email: user.email };
        localStorage.setItem('ff_iom_user', JSON.stringify(state.user));
        updateNav();
        showToast(`Welcome back ${username}!`);
        showPage('my-team');
    } else {
        showToast('Invalid credentials', 'error');
    }
}

function logout() {
    state.user = null;
    localStorage.removeItem('ff_iom_user');
    updateNav();
    showPage('home');
    showToast('Logged out');
}

function updateNav() {
    const navUser = document.getElementById('nav-user');
    const registerLink = document.getElementById('register-link');
    
    if (state.user) {
        navUser.style.display = 'flex';
        document.getElementById('nav-username').textContent = state.user.username;
        registerLink.style.display = 'none';
    } else {
        navUser.style.display = 'none';
        registerLink.style.display = '';
    }
}

function showLogin() {
    document.getElementById('register-form').style.display = 'none';
    document.getElementById('login-form').style.display = 'block';
}

function showRegister() {
    document.getElementById('register-form').style.display = 'block';
    document.getElementById('login-form').style.display = 'none';
}

// Teams
async function loadTeams() {
    const container = document.getElementById('teams-container');
    container.innerHTML = '<div class="loading">Loading teams...</div>';
    
    try {
        const divisions = await api('/api/teams/divisions');
        state.divisions = divisions;
        
        if (!divisions.length) {
            container.innerHTML = '<p>No teams loaded yet. Click "Refresh from API" to fetch.</p>';
            return;
        }
        
        let html = '';
        for (const div of divisions) {
            html += `
                <div class="division-section">
                    <div class="division-header">${div.name} (${div.teams.length} teams)</div>
                    <table class="team-table">
                        <thead>
                            <tr>
                                <th>Pos</th>
                                <th>Team</th>
                                <th>P</th>
                                <th>W</th>
                                <th>D</th>
                                <th>L</th>
                                <th>GD</th>
                                <th>Pts</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            for (const team of div.teams) {
                html += `
                            <tr>
                                <td class="team-position">${team.position || '-'}</td>
                                <td class="team-name">${team.name}</td>
                                <td>${team.games_played || 0}</td>
                                <td>-</td>
                                <td>-</td>
                                <td>-</td>
                                <td>-</td>
                                <td><strong>${team.points || 0}</strong></td>
                            </tr>
                `;
            }
            
            html += `
                        </tbody>
                    </table>
                </div>
            `;
        }
        
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
    }
}

async function refreshTeams() {
    try {
        const result = await api('/api/teams/refresh', { method: 'GET' });
        showToast(`Updated ${result.teams_updated} teams from ${result.divisions} divisions`);
        loadTeams();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// My Team
async function loadMyTeam() {
    const container = document.getElementById('my-team-container');
    container.innerHTML = '<div class="loading">Loading your team...</div>';
    
    if (!state.user) {
        container.innerHTML = '<p>Please <a href="#" onclick="showPage(\'register\')">register or login</a> first.</p>';
        return;
    }
    
    try {
        const team = await api(`/api/users/${state.user.id}/team`);
        
        let totalPoints = 0;
        let html = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
                <h3>${team.name}</h3>
                <span class="positive" style="font-size:1.5rem;font-weight:700;">${team.total_points} pts</span>
            </div>
            <div class="squad-grid">
        `;
        
        for (const player of team.squad) {
            totalPoints += player.total_points;
            const badges = [];
            if (player.is_captain) badges.push('<span class="captain-badge">C</span>');
            else if (player.is_vice_captain) badges.push('<span class="vice-badge">VC</span>');
            
            html += `
                <div class="squad-card">
                    ${badges.join('')}
                    <span class="position-badge">${player.position}</span>
                    <h4>${player.team.name}</h4>
                    <div class="points">${player.total_points}</div>
                </div>
            `;
        }
        
        html += '</div>';
        
        // Captain picker
        html += `
            <div style="margin-top:1.5rem;background:var(--dark);padding:1.5rem;border-radius:12px;border:1px solid rgba(255,255,255,0.1);">
                <h4>Set Captain</h4>
                <div style="display:flex;gap:1rem;margin-top:0.75rem;">
                    <select id="captain-select" style="flex:1;padding:0.5rem;border-radius:6px;background:var(--darker);color:var(--light);border:1px solid rgba(255,255,255,0.1);">
        `;
        
        for (const player of team.squad) {
            const selected = player.is_captain ? 'selected' : '';
            html += `<option value="${player.team_id}" ${selected}>${player.team.name}</option>`;
        }
        
        html += `</select>
                    <select id="vc-select" style="flex:1;padding:0.5rem;border-radius:6px;background:var(--darker);color:var(--light);border:1px solid rgba(255,255,255,0.1);">
        `;
        
        for (const player of team.squad) {
            const selected = player.is_vice_captain ? 'selected' : '';
            html += `<option value="${player.team_id}" ${selected}>${player.team.name}</option>`;
        }
        
        html += `</select>
                    <button class="btn btn-primary" onclick="setCaptain()">Set</button>
                </div>
            </div>
        `;
        
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
    }
}

async function setCaptain() {
    const captainId = parseInt(document.getElementById('captain-select').value);
    const vcId = parseInt(document.getElementById('vc-select').value);
    
    if (captainId === vcId) {
        showToast('Captain and Vice-Captain must be different', 'error');
        return;
    }
    
    try {
        await api(`/api/users/${state.user.id}/team/captain`, {
            method: 'PUT',
            body: JSON.stringify({
                captain_id: captainId,
                vice_captain_id: vcId,
            }),
        });
        
        showToast('Captain set!');
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// Leaderboard
async function loadLeaderboard() {
    const container = document.getElementById('leaderboard-container');
    container.innerHTML = '<div class="loading">Loading leaderboard...</div>';
    
    try {
        const data = await api('/api/leaderboard/');
        
        if (!data.entries.length) {
            container.innerHTML = '<p>No teams registered yet. Be the first!</p>';
            return;
        }
        
        let html = `
            <table class="leaderboard-table">
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Manager</th>
                        <th>Team</th>
                        <th>Points</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        for (const entry of data.entries) {
            html += `
                    <tr>
                        <td class="leaderboard-rank">${entry.rank}</td>
                        <td>${entry.username}</td>
                        <td>${entry.team_name}</td>
                        <td><strong class="positive">${entry.total_points}</strong></td>
                    </tr>
            `;
        }
        
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
    }
}

// Gameweeks
async function loadGameweeks() {
    const container = document.getElementById('gameweeks-container');
    container.innerHTML = '<div class="loading">Loading gameweeks...</div>';
    
    try {
        const data = await api('/api/gameweeks/current');
        
        if (!data.gameweek) {
            container.innerHTML = '<p>No active gameweek. Sync fixtures to create gameweeks.</p>';
            return;
        }
        
        const gw = data.gameweek;
        let html = `
            <div class="gameweek-card">
                <div class="gameweek-header">
                    <div>
                        <strong>Gameweek ${gw.number}</strong>
                        <span style="color:var(--gray);margin-left:0.5rem;">${gw.season}</span>
                    </div>
                    <span class="gameweek-status ${gw.closed ? 'status-closed' : 'status-active'}">
                        ${gw.closed ? 'Closed' : 'Active'}
                    </span>
                </div>
                <div class="gameweek-fixtures">
                    <p style="color:var(--gray);font-size:0.85rem;margin-bottom:0.5rem;">
                        Deadline: ${new Date(gw.deadline).toLocaleString()}
                    </p>
        `;
        
        for (const f of data.fixtures) {
            html += `
                    <div class="fixture-row">
                        <span class="fixture-team home">${f.home_team}</span>
                        <span class="fixture-score">${f.played ? `${f.home_score} - ${f.away_score}` : 'vs'}</span>
                        <span class="fixture-team away">${f.away_team}</span>
                    </div>
            `;
        }
        
        html += '</div></div>';
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
    }
}

async function syncGameweeks() {
    try {
        const result = await api('/api/gameweeks/sync', { method: 'POST' });
        showToast(`Synced ${result.fixtures_synced} fixtures across ${result.gameweeks} gameweeks`);
        loadGameweeks();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// Initialize
updateNav();

// Store users for login
function storeUser(user, password) {
    const stored = JSON.parse(localStorage.getItem('ff_iom_users') || '[]');
    const existing = stored.findIndex(u => u.username === user.username);
    if (existing >= 0) {
        stored[existing] = { id: user.id, username: user.username, email: user.email, password };
    } else {
        stored.push({ id: user.id, username: user.username, email: user.email, password });
    }
    localStorage.setItem('ff_iom_users', JSON.stringify(stored));
}

// Override register to also store password for login
const originalHandleRegister = handleRegister;
handleRegister = async function(e) {
    e.preventDefault();
    const password = document.getElementById('reg-password').value;
    
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const teamName = document.getElementById('reg-team-name').value;
    
    try {
        const user = await api('/api/users/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password }),
        });
        
        await api(`/api/users/${user.id}/team/create`, {
            method: 'POST',
            body: JSON.stringify({ team_name: teamName }),
        });
        
        storeUser(user, password);
        
        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        updateNav();
        showToast(`Welcome ${username}! Your team "${teamName}" has been created.`);
        showPage('my-team');
    } catch (err) {
        showToast(err.message, 'error');
    }
};
