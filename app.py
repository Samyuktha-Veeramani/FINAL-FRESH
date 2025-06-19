from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from mysql.connector import Error
from mysql.connector.pooling import MySQLConnectionPool
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import secrets

products = [
    {"id": "apple", "name": "Organic Apples", "price": 299},
    {"id": "carrot", "name": "Fresh Carrots", "price": 149},
    {"id": "egg", "name": "Farm Fresh Eggs", "price": 99},
    {"id": "mango", "name": "Fresh Mangoes", "price": 199},
    {"id": "sweet-potato", "name": "Sweet Potatoes", "price": 179},
    {"id": "lettuce", "name": "Green Lettuce", "price": 89},
    {"id": "banana", "name": "Organic Bananas", "price": 59},
    {"id": "bell-pepper", "name": "Red Bell Peppers", "price": 120},
    {"id": "tomato", "name": "Fresh Tomatoes", "price": 69},
    {"id": "orange", "name": "Juicy Oranges", "price": 129},
    {"id": "pineapple", "name": "Fresh Pineapples", "price": 149},
    {"id": "grapes", "name": "Red Grapes", "price": 249},
]

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))

db_config = {
    'user': 'admin',
    'password': 'freshbasketpw',
    'host': 'freshbasket.cydaiay6snh1.us-east-1.rds.amazonaws.com',
    'database': 'freshbasket',
    'port': 3306
}

cnxpool = MySQLConnectionPool(pool_name="mypool", pool_size=5, **db_config)

def get_db_connection():
    try:
        return cnxpool.get_connection()
    except Error as err:
        app.logger.error(f"Database connection error: {err}")
        return None

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        mobile = request.form.get('mobile')
        email = request.form.get('email')
        password = generate_password_hash(request.form.get('password'))
        default_address = request.form.get('default_address')
        role = request.form.get('role', 'customer')

        if not default_address:
            flash('Default address is required!')
            return redirect(url_for('register'))

        conn = get_db_connection()
        if not conn:
            flash('Database connection error. Please try again later.')
            return redirect(url_for('register'))

        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO fb_users (name, mobile, email, password, address, role) VALUES (%s, %s, %s, %s, %s, %s)',
                (name, mobile, email, password, default_address, role)
            )
            conn.commit()
            flash('Thank you for registering! Please log in to continue.', 'success')
            return redirect(url_for('login'))
        except Error as e:
            flash(f"Error: {e}", 'danger')
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        if not conn:
            flash('Database connection error. Please try again later.', 'danger')
            return redirect(url_for('login'))

        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute('SELECT * FROM fb_users WHERE email = %s', (email,))
            user = cursor.fetchone()

            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['role'] = user['role']
                flash('Login successful!', 'success')

                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('shop'))
            else:
                flash('Invalid email or password. Please try again.', 'danger')
        except Error as e:
            flash(f'An error occurred: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('login.html')

@app.route('/shop')
def shop():
    if 'user_id' not in session:
        flash('Please log in to access the shop.')
        return redirect(url_for('login'))
    return render_template('shop.html', products=products)

@app.route('/cart')
def view_cart():
    cart_items = session.get('cart', [])
    total_price = sum(item['price'] * item['quantity'] for item in cart_items)
    total_items = sum(item['quantity'] for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total_price=total_price, total_items=total_items)

@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return jsonify(success=False, message="User not logged in")

    data = request.get_json()
    delivery_address = data.get('address', 'Default Address')
    payment_method = data["payment_method"]
    items = data['items']
    total_price = data['total_price']

    conn = get_db_connection()
    if not conn:
        return jsonify(success=False, message="Database connection error.")

    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO fb_orders (user_id, delivery_address, payment_method, status, order_date, total_price) VALUES (%s, %s, %s, %s, %s, %s)",
            (session['user_id'], delivery_address, payment_method, 'Yet to Ship', datetime.now(), total_price)
        )
        order_id = cursor.lastrowid
        for item in items:
            cursor.execute(
                'INSERT INTO fb_order_items (order_id, item_name, quantity, price) VALUES (%s, %s, %s, %s)',
                (order_id, item['name'], item['quantity'], item['price'])
            )
        conn.commit()
        return jsonify(success=True)
    except Error as e:
        conn.rollback()
        return jsonify(success=False, message=str(e))
    finally:
        cursor.close()
        conn.close()

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash('You have been logged out.')
    return redirect(url_for('home'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT o.id AS order_id, o.status, o.total_price AS amount, u.name AS user_name, u.email AS user_email
            FROM fb_orders o
            JOIN fb_users u ON o.user_id = u.id
            ORDER BY o.id DESC
        """)
        orders = cursor.fetchall()
    except Error as e:
        flash(f"Error: {str(e)}", 'danger')
        orders = []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin_dashboard.html', orders=orders)

@app.route('/admin_product_management')
def admin_product_management():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM fb_products')
    products = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin_product_management.html', products=products)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO fb_products (name, price, description) VALUES (%s, %s, %s)',
                (name, price, description)
            )
            conn.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('admin_product_management'))
        except Error as e:
            conn.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('add_product.html')

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM fb_products WHERE id = %s', (product_id,))
    product = cursor.fetchone()

    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('admin_product_management'))

    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']

        try:
            cursor.execute(
                'UPDATE fb_products SET name = %s, price = %s, description = %s WHERE id = %s',
                (name, price, description, product_id)
            )
            conn.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('admin_product_management'))
        except Error as e:
            conn.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('edit_product.html', product=product)

@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM fb_products WHERE id = %s', (product_id,))
        conn.commit()
        flash('Product deleted successfully!', 'success')
    except Error as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_product_management'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
from mysql.connector import Error
from mysql.connector.pooling import MySQLConnectionPool
from werkzeug.security import generate_password_hash, check_password_hash
import os
import secrets


# Simulated database for products
products = [
    {"id": "apple", "name": "Organic Apples", "price": 299},
    {"id": "carrot", "name": "Fresh Carrots", "price": 149},
    {"id": "egg", "name": "Farm Fresh Eggs", "price": 99},
    {"id": "mango", "name": "Fresh Mangoes", "price": 199},
    {"id": "sweet-potato", "name": "Sweet Potatoes", "price": 179},
    {"id": "lettuce", "name": "Green Lettuce", "price": 89},
    {"id": "banana", "name": "Organic Bananas", "price": 59},
    {"id": "bell-pepper", "name": "Red Bell Peppers", "price": 120},
    {"id": "tomato", "name": "Fresh Tomatoes", "price": 69},
    {"id": "orange", "name": "Juicy Oranges", "price": 129},
    {"id": "pineapple", "name": "Fresh Pineapples", "price": 149},
    {"id": "grapes", "name": "Red Grapes", "price": 249},
]

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))
 

# Database configuration
db_config = {
    'user': 'admin',
    'password': 'freshbasketpw',
    'host': 'freshbasket.cydaiay6snh1.us-east-1.rds.amazonaws.com',
    'database': 'freshbasket',
    'port': 3306
}

cnxpool = MySQLConnectionPool(pool_name="mypool", pool_size=5, **db_config)

# Function to establish a database connection
def get_db_connection():
    try:
        return cnxpool.get_connection()
    except Error as err:
        app.logger.error(f"Database connection error: {err}")
        return None

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        mobile = request.form.get('mobile')
        email = request.form.get('email')
        password = generate_password_hash(request.form.get('password'))
        default_address = request.form.get('default_address')
        role = request.form.get('role', 'customer')  # Default to 'customer' if no role is selected

        if not default_address:
            flash('Default address is required!')
            return redirect(url_for('register'))

        conn = get_db_connection()
        if not conn:
            flash('Database connection error. Please try again later.')
            return redirect(url_for('register'))

        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (name, mobile, email, password, address, role) VALUES (%s, %s, %s, %s, %s, %s)',
                (name, mobile, email, password, default_address, role)  # Added role to the query
            )
            conn.commit()
            flash('Thank you for registering! Please log in to continue.', 'success')
            return redirect(url_for('login'))
        except Error as e:
            flash(f"Error: {e}", 'danger')
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        if not conn:
            flash('Database connection error. Please try again later.', 'danger')
            return redirect(url_for('login'))

        # Use a buffered cursor to handle unread results
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            # Execute the query
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()  # Fetch a single result

            if user and check_password_hash(user['password'], password):
                # Set session variables
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['role'] = user['role']
                flash('Login successful!', 'success')

                # Redirect based on user role
                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('shop'))
            else:
                # Handle invalid credentials
                flash('Invalid email or password. Please try again.', 'danger')
        except Error as e:
            # Log and display database errors
            flash(f'An error occurred: {str(e)}', 'danger')
        finally:
            # Ensure the cursor and connection are closed
            cursor.close()
            conn.close()

    # Render the login page for GET requests
    return render_template('login.html')



@app.route('/shop')
def shop():
    if 'user_id' not in session:
        flash('Please log in to access the shop.')
        return redirect(url_for('login'))  # Redirect to login page if not logged in
    
    return render_template('shop.html', products=products)


@app.route('/cart')
def view_cart():
    # Retrieve the cart from the session
    cart_items = session.get('cart', [])
    
    # Debugging: Print cart items to verify session retrieval
    print("Cart items:", cart_items)  # Debugging line
    
    # Calculate total price and total items in the cart
    total_price = sum(item['price'] * item['quantity'] for item in cart_items)
    total_items = sum(item['quantity'] for item in cart_items)

    # Return the cart view page with updated data
    return render_template('cart.html', cart_items=cart_items, total_price=total_price, total_items=total_items)


@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return jsonify(success=False, message="User not logged in")

    data = request.get_json()
    delivery_address = data.get('address', 'Default Address')
    payment_method = data["payment_method"]
    items = data['items']
    total_price = data['total_price']

    conn = get_db_connection()
    if not conn:
        return jsonify(success=False, message="Database connection error.")

    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO orders (user_id, delivery_address, payment_method, status, order_date, total_price) VALUES (%s, %s, %s, %s, %s, %s)",
            (session['user_id'], delivery_address, payment_method, 'Yet to Ship', datetime.now(), total_price)
        )
        order_id = cursor.lastrowid
        for item in items:
            cursor.execute(
                'INSERT INTO order_items (order_id, item_name, quantity, price) VALUES (%s, %s, %s, %s)',
                (order_id, item['name'], item['quantity'], item['price'])
            )
        conn.commit()
        return jsonify(success=True)
    except Error as e:
        conn.rollback()
        return jsonify(success=False, message=str(e))
    finally:
        cursor.close()
        conn.close()


@app.route('/logout')
def logout():
    session.pop('user_id', None)  # Remove user session data
    session.pop('user_name', None)
    flash('You have been logged out.')
    return redirect(url_for('home'))  # Redirect to home page

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT o.id AS order_id, o.status, o.amount, u.name AS user_name, u.email AS user_email
            FROM orders o
            JOIN users u ON o.user_id = u.id
            ORDER BY o.id DESC
        """)
        orders = cursor.fetchall()
    except Error as e:
        flash(f"Error: {str(e)}", 'danger')
        orders = []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin_dashboard.html', orders=orders)

@app.route('/admin_product_management')
def admin_product_management():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM products')
    products = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin_product_management.html', products=products)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO products (name, price, description) VALUES (%s, %s, %s)',
                (name, price, description)
            )
            conn.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('admin_product_management'))
        except Error as e:
            conn.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('add_product.html')

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute('SELECT * FROM products WHERE id = %s', (product_id,))
    product = cursor.fetchone()

    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('admin_product_management'))

    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        description = request.form['description']

        try:
            cursor.execute(
                'UPDATE products SET name = %s, price = %s, description = %s WHERE id = %s',
                (name, price, description, product_id)
            )
            conn.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('admin_product_management'))
        except Error as e:
            conn.rollback()
            flash(f'Error: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('edit_product.html', product=product)

@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'role' not in session or session['role'] != 'admin':
        flash('Access denied: Admins only.')
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('DELETE FROM products WHERE id = %s', (product_id,))
        conn.commit()
        flash('Product deleted successfully!', 'success')
    except Error as e:
        conn.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_product_management'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000,debug=True)
